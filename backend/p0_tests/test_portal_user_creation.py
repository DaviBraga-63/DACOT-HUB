import bcrypt
from bson import ObjectId
from concurrent.futures import ThreadPoolExecutor
import time

import requests


def test_tenant_admin_creates_login_capable_user_with_correct_scope_and_role(services):
    s, owner, other = services, services.restaurant(), services.restaurant()
    email = "new-tenant-user@example.com"

    created = s.call("POST", "/portal/users", headers=owner["headers"], json={
        "name": "Usuário do Restaurante A", "email": email,
        "role": "waiter",
    })
    assert created.status_code == 200, created.text
    assert created.json()["role"] == "waiter"
    assert "password_hash" not in created.json()
    password = created.json()["temp_password"]
    assert password

    stored = s.db.tenant_users.find_one({"_id": ObjectId(created.json()["id"])})
    assert stored["tenant_id"] == owner["tid"]
    assert stored["password_hash"] != password
    assert bcrypt.checkpw(password.encode(), stored["password_hash"].encode())

    identity = {"tid": owner["tid"], "uid": created.json()["id"], "headers": s.login(email, password)}
    context = s.call("GET", "/portal/context", headers=identity["headers"])
    assert context.status_code == 200
    assert context.json()["tenant"]["id"] == owner["tid"]
    assert context.json()["user"]["role"] == "waiter"
    assert s.exchange(s.handoff(identity)).status_code == 200

    assert s.call("GET", "/portal/users", headers=identity["headers"]).status_code == 403
    assert s.call("POST", "/portal/users", headers=identity["headers"], json={
        "name": "Sem permissão", "email": "forbidden@example.com", "role": "waiter",
    }).status_code == 403
    assert s.call("GET", f"/hub/tenants/{other['tid']}/users", headers=identity["headers"]).status_code == 403


def test_portal_user_creation_is_tenant_isolated_and_rejects_privilege_escalation(services):
    s, owner, other = services, services.restaurant(), services.restaurant()

    own_users = s.call("GET", "/portal/users", headers=owner["headers"])
    assert own_users.status_code == 200
    assert {u["id"] for u in own_users.json()} == {owner["uid"]}
    assert other["uid"] not in {u["id"] for u in own_users.json()}

    for role in ("super_admin", "viewer"):
        result = s.call("POST", "/portal/users", headers=owner["headers"], json={
            "name": "Escalada", "email": f"{role}@example.com", "role": role,
        })
        assert result.status_code == 400

    duplicate = s.call("POST", "/portal/users", headers=owner["headers"], json={
        "name": "Duplicado", "email": s.db.tenant_users.find_one({"_id": ObjectId(other["uid"])})["email"],
        "role": "manager",
    })
    assert duplicate.status_code == 409

    blank = s.call("POST", "/portal/users", headers=owner["headers"], json={
        "name": "   ", "email": "blank@example.com", "role": "manager",
    })
    assert blank.status_code == 400

    assert s.call("PATCH", f"/portal/users/{other['uid']}", headers=owner["headers"],
                  json={"name": "Outro tenant"}).status_code == 404
    assert s.call("POST", f"/portal/users/{other['uid']}/reset-password",
                  headers=owner["headers"]).status_code == 404


def test_complete_user_lifecycle_revokes_old_sessions_and_supports_new_password(services):
    s, owner = services, services.restaurant()
    email = "complete-lifecycle@example.com"
    created = s.call("POST", "/portal/users", headers=owner["headers"], json={
        "name": "Usuário Inicial", "email": email, "role": "waiter",
    })
    created.raise_for_status()
    uid = created.json()["id"]
    original_password = created.json()["temp_password"]
    user_headers = s.login(email, original_password)

    edited = s.call("PATCH", f"/portal/users/{uid}", headers=owner["headers"], json={
        "name": "Usuário Editado", "email": email, "role": "manager",
    })
    assert edited.status_code == 200
    assert edited.json()["name"] == "Usuário Editado"
    assert edited.json()["role"] == "manager"
    assert s.call("GET", "/portal/context", headers=user_headers).status_code == 401

    user_headers = s.login(email, original_password)
    identity = {"tid": owner["tid"], "uid": uid, "headers": user_headers}
    exchanged = s.exchange(s.handoff(identity))
    assert exchanged.status_code == 200
    orders_token = exchanged.json()["token"]
    assert s.order_me(orders_token).status_code == 200

    disabled = s.call("PATCH", f"/portal/users/{uid}", headers=owner["headers"],
                      json={"status": "inactive"})
    assert disabled.status_code == 200 and disabled.json()["status"] == "inactive"
    assert s.call("GET", "/portal/context", headers=user_headers).status_code == 401
    time.sleep(61)
    assert s.order_me(orders_token).status_code == 403

    enabled = s.call("PATCH", f"/portal/users/{uid}", headers=owner["headers"],
                     json={"status": "active"})
    assert enabled.status_code == 200 and enabled.json()["status"] == "active"
    assert s.call("GET", "/portal/context", headers=user_headers).status_code == 401
    assert s.order_me(orders_token).status_code == 403

    fresh_headers = s.login(email, original_password)
    reset = s.call("POST", f"/portal/users/{uid}/reset-password", headers=owner["headers"])
    assert reset.status_code == 200
    new_password = reset.json()["temp_password"]
    stored = s.db.tenant_users.find_one({"_id": ObjectId(uid)})
    assert stored["password_hash"] != new_password
    assert bcrypt.checkpw(new_password.encode(), stored["password_hash"].encode())
    assert s.call("GET", "/portal/context", headers=fresh_headers).status_code == 401
    assert requests.post(s.hub + "/api/auth/login", json={"email": email, "password": original_password}, timeout=10).status_code == 401
    final_headers = s.login(email, new_password)
    assert s.call("GET", "/portal/context", headers=final_headers).json()["user"]["role"] == "manager"
    assert s.exchange(s.handoff({"tid": owner["tid"], "uid": uid, "headers": final_headers})).status_code == 200


def test_last_admin_and_concurrent_duplicate_guards(services):
    s, owner = services, services.restaurant()
    only_admin = s.call("PATCH", f"/hub/tenants/{owner['tid']}/users/{owner['uid']}",
                        json={"status": "inactive"})
    assert only_admin.status_code == 400

    second = s.call("POST", "/portal/users", headers=owner["headers"], json={
        "name": "Segundo Admin", "email": "second-admin@example.com", "role": "admin",
    })
    second.raise_for_status()
    second_headers = s.login("second-admin@example.com", second.json()["temp_password"])

    def demote(headers, uid):
        return s.call("PATCH", f"/portal/users/{uid}", headers=headers, json={"role": "manager"})

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda args: demote(*args), [
            (owner["headers"], second.json()["id"]), (second_headers, owner["uid"]),
        ]))
    assert sum(r.status_code == 200 for r in results) == 1
    assert s.db.tenant_users.count_documents(
        {"tenant_id": owner["tid"], "status": "active", "role": "admin"}) == 1

    duplicate_email = "concurrent-duplicate@example.com"
    payload = {"name": "Concorrente", "email": duplicate_email, "role": "waiter"}
    active_admin = s.db.tenant_users.find_one(
        {"tenant_id": owner["tid"], "status": "active", "role": "admin"})
    admin_headers = owner["headers"] if str(active_admin["_id"]) == owner["uid"] else second_headers
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(
            lambda _: s.call("POST", "/portal/users", headers=admin_headers, json=payload), range(2)))
    assert sorted(r.status_code for r in results) == [200, 409]
