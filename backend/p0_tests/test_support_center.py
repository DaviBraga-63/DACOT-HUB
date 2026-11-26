"""Exercise Support over authenticated HTTP with the disposable P0 MongoDB."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

from bson import ObjectId


PORTAL = "/portal/support"
HUB = "/hub/support"


def _owner(services):
    key = uuid4().hex
    email = f"support-{key}@example.com"
    name = f"Restaurante suporte {key}"
    created = services.call("POST", "/hub/tenants", json={
        "name": name, "owner_name": "Proprietário Suporte", "email": email, "status": "active",
    })
    created.raise_for_status()
    tenant_id = created.json()["id"]
    owner = services.db.tenant_users.find_one({"tenant_id": tenant_id, "email": email})
    reset = services.call("POST", f"/hub/tenants/{tenant_id}/users/{owner['_id']}/reset-password")
    reset.raise_for_status()
    return {
        "tid": tenant_id, "uid": owner["_id"], "name": name, "email": email,
        "headers": services.login(email, reset.json()["temp_password"]),
    }


def _staff(services, role):
    key = uuid4().hex
    email = f"support-{key}@example.com"
    name = f"Administrador Interno {key}"
    created = services.call("POST", "/hub/users", json={
        "name": name, "email": email, "role": role, "password": services.password,
    })
    created.raise_for_status()
    return name, services.login(email, services.password)


def _ticket_payload(subject, *, category="technical", message="Descrição do chamado"):
    return {"subject": subject, "category": category, "message": message, "request_id": str(uuid4())}


def _create(services, owner, subject, **kwargs):
    response = services.call("POST", f"{PORTAL}/tickets", headers=owner["headers"],
                             json=_ticket_payload(subject, **kwargs))
    response.raise_for_status()
    return response.json()["id"]


def _get(services, scope, ticket_id, headers, **kwargs):
    response = services.call("GET", f"{scope}/tickets/{ticket_id}", headers=headers, **kwargs)
    response.raise_for_status()
    return response.json()


def _unread(services, scope, headers):
    response = services.call("GET", f"{scope}/unread", headers=headers)
    response.raise_for_status()
    return response.json()["count"]


def _read(services, scope, ticket_id, headers, through):
    response = services.call("POST", f"{scope}/tickets/{ticket_id}/read", headers=headers,
                             json={"through": through})
    response.raise_for_status()


def _mutate(services, scope, ticket_id, headers, action, **payload):
    response = services.call("POST", f"{scope}/tickets/{ticket_id}/{action}", headers=headers,
                             json={"request_id": str(uuid4()), **payload})
    response.raise_for_status()
    return response.json()


def _parallel(*calls):
    barrier = Barrier(len(calls))

    def run(call):
        barrier.wait(timeout=10)
        return call()

    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        futures = [pool.submit(run, call) for call in calls]
        return [future.result(timeout=30) for future in futures]


def test_ticket_lifecycle_and_private_independent_read_state(services):
    owner = _owner(services)
    responder_name, responder = _staff(services, "admin")
    staff_count = _unread(services, HUB, services.staff)
    responder_count = _unread(services, HUB, responder)
    subject = "Dúvida sobre meu restaurante"
    ticket_id = _create(services, owner, subject, category="usage")

    assert _unread(services, PORTAL, owner["headers"]) == 0
    assert _unread(services, HUB, services.staff) == staff_count + 1
    assert _unread(services, HUB, responder) == responder_count + 1
    admin_view = _get(services, HUB, ticket_id, responder)
    assert admin_view["ticket"]["status"] == "awaiting_support"
    assert admin_view["ticket"]["subject"] == subject
    assert admin_view["ticket"]["category"] == "usage"
    assert admin_view["restaurant"]["name"] == owner["name"]
    assert admin_view["restaurant"]["email"] == owner["email"]
    assert not admin_view["restaurant"].get("whatsapp")
    # The list and opening the detail must leave workflow and both counters intact.
    assert _unread(services, HUB, responder) == responder_count + 1
    _read(services, HUB, ticket_id, responder, admin_view["through"])
    assert _unread(services, HUB, responder) == responder_count
    assert _unread(services, HUB, services.staff) == staff_count + 1
    assert _get(services, HUB, ticket_id, responder)["ticket"]["status"] == "awaiting_support"

    _mutate(services, HUB, ticket_id, responder, "messages", message="Olá! Em que podemos ajudar?")
    assert _unread(services, PORTAL, owner["headers"]) == 1
    customer_view = _get(services, PORTAL, ticket_id, owner["headers"])
    assert customer_view["ticket"]["status"] == "awaiting_customer"
    reply = customer_view["messages"][-1]
    assert reply["author_type"] == "staff" and reply["author_label"] == "Equipe DACOT"
    assert responder_name not in str(customer_view)
    assert not customer_view.get("restaurant")
    assert not {"reader", "reader_id", "read_at", "seen_seq", "read_states", "typing", "presence"} & (
        customer_view.keys() | customer_view["ticket"].keys() | reply.keys()
    )
    _read(services, PORTAL, ticket_id, owner["headers"], customer_view["through"])
    assert _unread(services, PORTAL, owner["headers"]) == 0
    assert _get(services, PORTAL, ticket_id, owner["headers"])["ticket"]["status"] == "awaiting_customer"

    _mutate(services, PORTAL, ticket_id, owner["headers"], "messages", message="Segue a informação solicitada.")
    waiting = _get(services, HUB, ticket_id, responder)
    assert waiting["ticket"]["status"] == "awaiting_support"
    assert _unread(services, HUB, responder) == responder_count + 1
    _mutate(services, HUB, ticket_id, responder, "status", status="resolved")
    resolved = _get(services, PORTAL, ticket_id, owner["headers"])
    assert resolved["ticket"]["status"] == "resolved"
    assert _unread(services, PORTAL, owner["headers"]) == 1
    assert resolved["messages"][-1]["kind"] == "resolved"
    _mutate(services, PORTAL, ticket_id, owner["headers"], "status", status="awaiting_support")
    reopened = _get(services, PORTAL, ticket_id, owner["headers"])
    assert reopened["ticket"]["status"] == "awaiting_support"
    assert reopened["messages"][:-1] == resolved["messages"]
    assert reopened["messages"][-1]["kind"] == "reopened"
    _mutate(services, HUB, ticket_id, responder, "status", status="resolved")
    _mutate(services, HUB, ticket_id, responder, "status", status="awaiting_support")
    assert _get(services, HUB, ticket_id, responder)["ticket"]["status"] == "awaiting_support"


def test_support_auth_rejects_foreign_tenants_viewers_and_forged_identity(services):
    owner, foreign = _owner(services), _owner(services)
    _, viewer = _staff(services, "viewer")
    ticket_id = _create(services, owner, "Chamado privado de um restaurante")
    ticket = f"/tickets/{ticket_id}"
    message = {"message": "Tentativa indevida", "request_id": str(uuid4())}
    assert services.call("GET", f"{PORTAL}/unread", headers={}).status_code == 401
    assert services.call("GET", f"{HUB}/tickets", headers=viewer).status_code == 403
    assert services.call("GET", f"{HUB}/unread", headers=viewer).status_code == 403
    assert services.call("GET", HUB + ticket, headers=viewer).status_code == 403
    assert services.call("POST", f"{HUB}{ticket}/messages", headers=viewer, json=message).status_code == 403
    assert services.call("GET", f"{HUB}/tickets", headers=owner["headers"]).status_code == 403
    assert services.call("GET", f"{PORTAL}/tickets", headers=services.staff).status_code == 403
    assert services.call("GET", f"{PORTAL}/tickets/not-an-id", headers=owner["headers"]).status_code == 404
    for suffix, payload in (
        ("/messages", message), ("/read", {"through": 1}),
        ("/status", {"status": "awaiting_support", "request_id": str(uuid4())}),
    ):
        response = services.call("POST", PORTAL + ticket + suffix, headers=foreign["headers"], json=payload)
        assert response.status_code == 404
    assert services.call("GET", PORTAL + ticket, headers=foreign["headers"]).status_code == 404
    foreign_list = services.call("GET", f"{PORTAL}/tickets", headers=foreign["headers"],
                                 params={"tenant_id": owner["tid"]})
    assert foreign_list.status_code == 200 and foreign_list.json()["total"] == 0
    forbidden_fields = services.call("POST", f"{PORTAL}{ticket}/messages", headers=owner["headers"],
                                     json={**message, "tenant_id": foreign["tid"], "author_type": "staff"})
    assert forbidden_fields.status_code == 422
    resolve = services.call("POST", f"{PORTAL}{ticket}/status", headers=owner["headers"],
                            json={"status": "resolved", "request_id": str(uuid4())})
    assert resolve.status_code in {403, 422}
    assert len(_get(services, PORTAL, ticket_id, owner["headers"])["messages"]) == 1

    # The session is live, but the current identity is no longer an administrator.
    services.db.tenant_users.update_one({"_id": owner["uid"]}, {"$set": {"role": "waiter"}})
    assert services.call("GET", f"{PORTAL}/tickets", headers=owner["headers"]).status_code == 403


def test_concurrent_retries_are_idempotent_and_read_keeps_new_messages_unread(services):
    owner = _owner(services)
    _, staff = _staff(services, "admin")
    payload = _ticket_payload("Chamado com criação concorrente")
    url = f"{PORTAL}/tickets"

    def create():
        response = services.call("POST", url, headers=owner["headers"], json=payload)
        response.raise_for_status()
        return response.json()["id"]

    ticket_id, same_id = _parallel(create, create)
    assert ticket_id == same_id
    conflict = services.call("POST", url, headers=owner["headers"], json={**payload, "message": "Outro texto"})
    assert conflict.status_code == 409
    listed = services.call("GET", url, headers=owner["headers"])
    assert listed.status_code == 200 and listed.json()["total"] == 1
    before = _get(services, HUB, ticket_id, staff)
    assert len(before["messages"]) == 1

    new_message = {"message": "Mensagem produzida enquanto o ticket era lido", "request_id": str(uuid4())}

    def send():
        response = services.call("POST", f"{PORTAL}/tickets/{ticket_id}/messages", headers=owner["headers"],
                                 json=new_message)
        response.raise_for_status()

    _parallel(send, send, lambda: _read(services, HUB, ticket_id, staff, before["through"]))
    after = _get(services, HUB, ticket_id, staff)
    assert len(after["messages"]) == 2
    assert after["ticket"]["unread"] is True
    assert after["ticket"]["status"] == "awaiting_support"
    assert after["messages"][-1]["text"] == new_message["message"]
    assert after["through"] > before["through"]
    older_page = _get(services, HUB, ticket_id, staff, params={"before": after["through"]})
    assert older_page["through"] == before["through"] and older_page["messages"] == before["messages"]
    assert older_page["ticket"]["unread"] is True
    future_read = services.call("POST", f"{HUB}/tickets/{ticket_id}/read", headers=staff,
                                json={"through": after["through"] + 100})
    assert future_read.status_code == 422
    assert _get(services, HUB, ticket_id, staff)["ticket"]["unread"] is True
    _read(services, HUB, ticket_id, staff, after["through"])
    _read(services, HUB, ticket_id, staff, before["through"])
    assert _get(services, HUB, ticket_id, staff)["ticket"]["unread"] is False

    _parallel(
        lambda: _mutate(services, HUB, ticket_id, staff, "messages", message="Resposta administrativa simultânea"),
        lambda: _mutate(services, PORTAL, ticket_id, owner["headers"], "messages", message="Complemento simultâneo"),
    )
    final = _get(services, HUB, ticket_id, staff)
    assert len(final["messages"]) == 4
    assert {item["text"] for item in final["messages"][-2:]} == {
        "Resposta administrativa simultânea", "Complemento simultâneo",
    }
    expected = "awaiting_support" if final["messages"][-1]["author_type"] == "restaurant" else "awaiting_customer"
    assert final["ticket"]["status"] == expected


def test_ticket_validation_search_filters_pagination_and_literal_text(services):
    owner = _owner(services)
    owner_headers = owner["headers"]
    for override in (
        {"subject": "  "}, {"subject": "s" * 121}, {"message": "  \n "},
        {"message": "m" * 4001}, {"category": "desconhecida"}, {"request_id": "inválido"},
    ):
        response = services.call("POST", f"{PORTAL}/tickets", headers=owner_headers,
                                 json={**_ticket_payload("Assunto válido"), **override})
        assert response.status_code == 422

    literal = "Texto literal\n<script>alert('fixture')</script>\nsegunda linha"
    technical = _create(services, owner, "Erro visual [registro]", message=literal)
    billing = _create(services, owner, "Dúvida de cobrança", category="billing")
    detail = _get(services, PORTAL, technical, owner_headers)
    assert detail["messages"][0]["text"] == literal
    public_number = detail["ticket"]["number"]
    assert public_number
    for params, expected in (
        ({"q": str(public_number)}, technical), ({"q": "[registro]"}, technical),
        ({"q": "COBRANÇA", "category": "billing"}, billing),
    ):
        response = services.call("GET", f"{PORTAL}/tickets", headers=owner_headers, params=params)
        response.raise_for_status()
        assert [item["id"] for item in response.json()["items"]] == [expected]
    first, second = [services.call("GET", f"{PORTAL}/tickets", headers=owner_headers,
                                   params={"page": page, "page_size": 1}).json() for page in (1, 2)]
    assert first["total"] == second["total"] == 2
    assert first["page_size"] == second["page_size"] == 1
    assert {first["items"][0]["id"], second["items"][0]["id"]} == {technical, billing}

    _mutate(services, HUB, billing, services.staff, "status", status="resolved")
    for status, expected in (("open", technical), ("resolved", billing)):
        query = services.call("GET", f"{PORTAL}/tickets", headers=owner_headers, params={"status": status})
        assert query.status_code == 200 and [item["id"] for item in query.json()["items"]] == [expected]
    staff_query = services.call("GET", f"{HUB}/tickets", params={"q": owner["name"]})
    assert staff_query.status_code == 200 and staff_query.json()["total"] == 2


def test_support_persists_through_hub_restart_with_orders_offline(services):
    owner = _owner(services)
    services.stop("orders")
    try:
        ticket_id = _create(services, owner, "Suporte independente dos módulos")
        first = _get(services, HUB, ticket_id, services.staff)
        _read(services, HUB, ticket_id, services.staff, first["through"])
        services.restart_hub()
        restored = _get(services, HUB, ticket_id, services.staff)
        assert restored["ticket"]["status"] == "awaiting_support"
        assert restored["messages"] == first["messages"]
        assert restored["ticket"]["unread"] is False
        _mutate(services, HUB, ticket_id, services.staff, "messages", message="Resposta com Pedidos offline")
        assert _unread(services, PORTAL, owner["headers"]) == 1
    finally:
        services.restart_orders()


def test_first_message_stays_visible_when_history_write_is_interrupted(services):
    owner = _owner(services)
    payload = _ticket_payload("Recuperação da primeira mensagem")
    created = services.call("POST", f"{PORTAL}/tickets", headers=owner["headers"], json=payload)
    created.raise_for_status()
    ticket_id = created.json()["id"]
    storage_id = ObjectId(ticket_id)
    messages = services.db.support_messages
    tickets = services.db.support_tickets

    # Recreate the durable state immediately after the ticket commit and
    # before the separate history record was materialized.
    first = messages.find_one({"ticket_id": storage_id, "seq": 1})
    assert first is not None
    tickets.update_one({"_id": storage_id}, {"$set": {"pending_event": first}})
    messages.delete_one({"_id": first["_id"]})

    visible = _get(services, PORTAL, ticket_id, owner["headers"])
    assert [event["text"] for event in visible["messages"]] == [payload["message"]]
    retry = services.call("POST", f"{PORTAL}/tickets", headers=owner["headers"], json=payload)
    assert retry.status_code == 200 and retry.json()["id"] == ticket_id
    assert messages.count_documents({"ticket_id": storage_id}) == 1
    assert "pending_event" not in tickets.find_one({"_id": storage_id})
    assert _get(services, PORTAL, ticket_id, owner["headers"])["messages"] == visible["messages"]


def test_admin_support_details_accept_whatsapp_without_email(services):
    owner = _owner(services)
    phone = "+5511" + str(900000000 + (uuid4().int % 100000000))
    services.db.tenants.update_one({"_id": ObjectId(owner["tid"])}, {
        "$unset": {"email": ""}, "$set": {"mobile_phone": phone, "phone_user_id": str(owner["uid"])},
    })
    services.db.tenant_users.update_one({"_id": owner["uid"]}, {
        "$unset": {"email": ""}, "$set": {"phone_number": phone},
    })
    ticket_id = _create(services, owner, "Ajuda de conta sem e-mail", category="account")
    restaurant = _get(services, HUB, ticket_id, services.staff)["restaurant"]
    assert restaurant["whatsapp"] == phone
    assert not restaurant.get("email")
