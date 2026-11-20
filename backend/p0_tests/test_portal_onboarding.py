"""P0 coverage for the optional first client access and client portal boundary."""

import secrets
import uuid
import hashlib

from bson import ObjectId
from pymongo.errors import DuplicateKeyError
import pytest
import requests


def _onboard_payload(tag, **extra):
    return {
        "name": f"Restaurante {tag}",
        "owner_name": "Responsável inicial",
        "email": f"owner-{tag}@example.com",
        "status": "trial",
        **extra,
    }


def _login_with_identifier(service, identifier, password):
    return requests.post(
        service.hub + "/api/auth/login",
        json={"identifier": identifier, "password": password},
        headers={"X-DACOT-Tab-Session": str(uuid.uuid4())}, timeout=10,
    )


def _unique_test_phone(service):
    """Return a valid Brazilian mobile number unused by this disposable DB."""
    while True:
        phone = f"+55119{secrets.randbelow(100_000_000):08d}"
        if not service.db.tenant_users.find_one({"phone_number": phone}):
            return phone


def test_staff_onboarding_always_creates_and_links_the_initial_portal_owner(services):
    service = services
    tag = secrets.token_hex(5)
    email = f"manager-{tag}@example.com"
    with_access = service.call("POST", "/hub/tenants/onboard", json=_onboard_payload(
        tag, owner_name="Gerente inicial", email=email,
    ))
    assert with_access.status_code == 200, with_access.text
    body = with_access.json()
    assert body["initial_access_created"] is True
    assert body["users_count"] == 1
    assert body["invitation"] == "email_sent"
    assert "temp_password" not in with_access.text

    manager = service.db.tenant_users.find_one({"tenant_id": body["id"], "email": email})
    assert manager and manager["role"] == "manager"
    assert manager["name"] == "Gerente inicial"
    assert manager["user_type"] == "restaurant"
    assert manager["password_reset_required"] is True
    tenant = service.db.tenants.find_one({"_id": ObjectId(body["id"])})
    assert tenant["portal_owner_user_id"] == str(manager["_id"])
    assert body["portal_owner_configured"] is True
    assert service.db.password_reset_tokens.count_documents({"user_id": str(manager["_id"]), "used": False}) == 1
    password_reset = service.call("POST", f"/hub/tenants/{body['id']}/users/{manager['_id']}/reset-password")
    assert password_reset.status_code == 200, password_reset.text
    owner_headers = service.login(email, password_reset.json()["temp_password"])
    assert service.call("GET", "/portal/context", headers=owner_headers).status_code == 200
    # Onboarding never activates a product or assumes an individual grant.
    assert service.db.tenant_modules.count_documents({"tenant_id": body["id"]}) == 0
    assert service.db.module_user_grants.count_documents({"tenant_id": body["id"]}) == 0


def test_onboarding_uses_responsible_and_email_as_the_only_owner_identity(services):
    """Deprecated duplicate access keys cannot create a second owner identity."""
    service = services
    tag = secrets.token_hex(5)
    response = service.call("POST", "/hub/tenants/onboard", json=_onboard_payload(
        tag,
        owner_name="Responsável oficial",
        email=f"official-{tag}@example.com",
        # Older clients may still send these fields.  The onboarding identity
        # must remain the restaurant responsible and email above.
        access_name="Nome alternativo",
        access_email=f"alternate-{tag}@example.com",
        phone="", address="", notes="",
    ))
    assert response.status_code == 200, response.text
    body = response.json()
    owners = list(service.db.tenant_users.find({"tenant_id": body["id"]}))
    assert len(owners) == 1
    assert owners[0]["name"] == "Responsável oficial"
    assert owners[0]["email"] == f"official-{tag}@example.com"
    assert body["phone"] == body["mobile_phone"] == body["address"] == body["notes"] == ""


def test_onboarding_requires_only_the_contact_selected_for_first_access(services):
    service = services
    before = service.db.tenants.count_documents({})
    email_missing = service.call("POST", "/hub/tenants/onboard", json={
        "name": "Sem e-mail", "owner_name": "Responsável", "email": "",
        "access_channel": "email",
    })
    assert email_missing.status_code == 400
    whatsapp_missing = service.call("POST", "/hub/tenants/onboard", json={
        "name": "Sem WhatsApp", "owner_name": "Responsável",
        "access_channel": "whatsapp",
    })
    assert whatsapp_missing.status_code == 400
    assert service.db.tenants.count_documents({}) == before


def test_confirmed_whatsapp_only_owner_can_login_and_recover_without_email(services):
    service = services
    tag = secrets.token_hex(5)
    phone = _unique_test_phone(service)
    created = service.call("POST", "/hub/tenants/onboard", json={
        "name": f"WhatsApp {tag}", "owner_name": "Responsável WhatsApp",
        "email": "", "mobile_phone": phone, "access_channel": "whatsapp",
        "phone": "", "address": "", "notes": "",
    })
    assert created.status_code == 200, created.text
    tid = created.json()["id"]
    owner = service.db.tenant_users.find_one({"tenant_id": tid})
    assert owner and "email" not in owner
    assert service.db.tenants.find_one({"_id": ObjectId(tid)})["portal_owner_user_id"] == str(owner["_id"])

    # Exercise the real proof-of-possession continuation without exposing a
    # production credential: replace only this disposable test token hash.
    raw_confirmation = secrets.token_urlsafe(32)
    service.db.owner_contact_confirmations.update_one(
        {"tenant_id": tid, "owner_user_id": str(owner["_id"]), "kind": "whatsapp"},
        {"$set": {"token_hash": hashlib.sha256(raw_confirmation.encode()).hexdigest()}},
    )
    confirmed = requests.post(service.hub + "/api/auth/confirm-owner-whatsapp", json={"token": raw_confirmation}, timeout=10)
    assert confirmed.status_code == 200, confirmed.text
    continuation = confirmed.json()["continuation_token"]
    assert continuation
    reset = requests.post(service.hub + "/api/auth/reset-password", json={
        "token": continuation, "password": service.password,
    }, timeout=10)
    assert reset.status_code == 200, reset.text
    login = _login_with_identifier(service, phone, service.password)
    assert login.status_code == 200, login.text

    recovery = requests.post(service.hub + "/api/auth/forgot-password", json={
        "identifier": phone, "channel": "whatsapp",
    }, timeout=10)
    assert recovery.status_code == 200
    assert service.db.password_reset_tokens.count_documents({"user_id": str(owner["_id"]), "used": False}) == 1


def test_phone_login_requires_confirmed_unique_binding(services):
    service = services
    tag = secrets.token_hex(5)
    phone = "+5511912345679"
    first = service.call("POST", "/hub/tenants/onboard", json={
        "name": f"Primeiro {tag}", "owner_name": "Primeiro", "email": f"first-{tag}@example.com",
    })
    second = service.call("POST", "/hub/tenants/onboard", json={
        "name": f"Segundo {tag}", "owner_name": "Segundo", "email": f"second-{tag}@example.com",
        "mobile_phone": phone, "access_channel": "whatsapp",
    })
    assert first.status_code == second.status_code == 200
    first_owner = service.db.tenant_users.find_one({"tenant_id": first.json()["id"]})
    second_owner = service.db.tenant_users.find_one({"tenant_id": second.json()["id"]})
    service.db.tenant_users.update_one({"_id": first_owner["_id"]}, {"$set": {"phone_number": phone}})
    # A typed-but-unconfirmed number cannot authenticate even once the owner
    # has a valid password; only phone_user_id establishes that binding.
    reset = service.call("POST", f"/hub/tenants/{first.json()['id']}/users/{first_owner['_id']}/reset-password")
    assert reset.status_code == 200
    assert _login_with_identifier(service, phone, reset.json()["temp_password"]).status_code == 401
    # The partial unique index then prevents it being bound to a second identity.
    with pytest.raises(DuplicateKeyError):
        service.db.tenant_users.update_one({"_id": second_owner["_id"]}, {"$set": {"phone_number": phone}})


def test_owner_with_both_confirmed_contacts_can_use_either_to_login(services):
    service = services
    tag = secrets.token_hex(5)
    email, phone = f"both-{tag}@example.com", "+5511912345680"
    created = service.call("POST", "/hub/tenants/onboard", json={
        "name": f"Dois contatos {tag}", "owner_name": "Responsável", "email": email,
        "mobile_phone": phone, "access_channel": "email",
    })
    assert created.status_code == 200, created.text
    tid = created.json()["id"]
    owner = service.db.tenant_users.find_one({"tenant_id": tid, "email": email})
    service.db.tenant_users.update_one({"_id": owner["_id"]}, {"$set": {
        "phone_number": phone, "phone_binding_version": "confirmed-binding",
    }})
    service.db.tenants.update_one({"_id": ObjectId(tid)}, {"$set": {"phone_user_id": str(owner["_id"])}})
    reset = service.call("POST", f"/hub/tenants/{tid}/users/{owner['_id']}/reset-password")
    assert reset.status_code == 200
    password = reset.json()["temp_password"]
    assert service.login(email, password)
    assert _login_with_identifier(service, phone, password).status_code == 200


def test_email_delivery_failure_keeps_one_recoverable_owner_without_reporting_success(services):
    service = services
    tag = secrets.token_hex(5)
    email = f"email-failure-{tag}@example.com"
    previous = service.env.get("DACOT_LOCAL_INTEGRATION")
    service.env["DACOT_LOCAL_INTEGRATION"] = "0"
    try:
        service.restart_hub()
        response = service.call("POST", "/hub/tenants/onboard", json=_onboard_payload(tag, email=email))
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["invitation"] == "email_delivery_failed"
        owner = service.db.tenant_users.find_one({"tenant_id": body["id"], "email": email})
        tenant = service.db.tenants.find_one({"_id": ObjectId(body["id"])})
        assert owner and tenant["portal_owner_user_id"] == str(owner["_id"])
        assert owner["password_reset_required"] is True
        assert service.db.password_reset_tokens.count_documents({"user_id": str(owner["_id"]), "used": False}) == 1
        duplicate = service.call("POST", "/hub/tenants/onboard", json=_onboard_payload(
            secrets.token_hex(5), email=email,
        ))
        assert duplicate.status_code == 409
    finally:
        if previous is None:
            service.env.pop("DACOT_LOCAL_INTEGRATION", None)
        else:
            service.env["DACOT_LOCAL_INTEGRATION"] = previous
        service.restart_hub()


def test_legacy_tenant_creation_route_uses_the_same_owner_flow(services):
    service = services
    tag = secrets.token_hex(5)
    response = service.call("POST", "/hub/tenants", json=_onboard_payload(tag))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["initial_access_created"] is True
    assert body["portal_owner_configured"] is True
    owner = service.db.tenant_users.find_one({"tenant_id": body["id"], "email": body["email"]})
    assert owner and owner["password_reset_required"] is True
    assert service.db.tenants.find_one({"_id": ObjectId(body["id"])}).get("portal_owner_user_id") == str(owner["_id"])


def test_onboarding_is_staff_write_only_and_duplicate_access_leaves_no_partial_tenant(services):
    service = services
    viewer_email = f"viewer-{secrets.token_hex(5)}@example.com"
    viewer = service.call("POST", "/hub/users", json={
        "name": "Somente leitura", "email": viewer_email, "role": "viewer", "password": service.password,
    })
    viewer.raise_for_status()
    viewer_headers = service.login(viewer_email, service.password)
    assert service.call("POST", "/hub/tenants/onboard", headers=viewer_headers,
                        json=_onboard_payload(secrets.token_hex(5))).status_code == 403

    existing = service.restaurant()
    existing_email = service.db.tenant_users.find_one({"_id": ObjectId(existing["uid"])} )["email"]
    before = service.db.tenants.count_documents({})
    duplicate = service.call("POST", "/hub/tenants/onboard", json=_onboard_payload(
        secrets.token_hex(5), email=existing_email,
    ))
    assert duplicate.status_code == 409
    assert service.db.tenants.count_documents({}) == before

    ownerless = service.call("POST", "/hub/tenants/onboard", json=_onboard_payload(
        secrets.token_hex(5), create_hub_access=False,
    ))
    assert ownerless.status_code == 422
    assert service.db.tenants.count_documents({}) == before


def test_portal_exposes_only_active_released_orders_and_non_owner_cannot_log_in(services):
    service, restaurant = services, services.restaurant()
    context = service.call("GET", "/portal/context", headers=restaurant["headers"])
    assert context.status_code == 200, context.text
    assert [module["key"] for module in context.json()["modules"]] == ["orders"]

    manager_email = f"manager-{secrets.token_hex(5)}@example.com"
    manager = service.call("POST", f"/hub/tenants/{restaurant['tid']}/users", json={
        "name": "Gerente", "email": manager_email, "role": "manager", "password": service.password,
    })
    manager.raise_for_status()
    grant = service.call(
        "PUT", f"/hub/tenants/{restaurant['tid']}/modules/orders/users/{manager.json()['id']}/access",
        json={"active": True},
    )
    assert grant.status_code == 200
    non_owner_login = requests.post(
        service.hub + "/api/auth/login", json={"email": manager_email, "password": service.password},
        headers={"X-DACOT-Tab-Session": secrets.token_urlsafe(24)}, timeout=10,
    )
    assert non_owner_login.status_code == 401

    assert service.call("POST", f"/hub/tenants/{restaurant['tid']}/modules/orders/deactivate").status_code == 200
    inactive_context = service.call("GET", "/portal/context", headers=restaurant["headers"])
    assert inactive_context.status_code == 200
    assert inactive_context.json()["modules"] == []
    assert service.call("POST", "/portal/modules/orders/launch-token", headers=restaurant["headers"]).status_code == 400
