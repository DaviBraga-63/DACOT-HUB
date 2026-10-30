import bcrypt
from bson import ObjectId
from concurrent.futures import ThreadPoolExecutor

import requests


def grant_orders_access(services, tenant_id, user_id):
    response = services.call(
        "PUT", f"/hub/tenants/{tenant_id}/modules/orders/users/{user_id}/access",
        json={"active": True},
    )
    assert response.status_code == 200, response.text


def test_portal_owner_creates_passworded_operational_user_without_hub_portal_access(services):
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

    grant_orders_access(s, owner["tid"], created.json()["id"])
    # Credentials remain Hub-owned for the direct Pedidos flow, but employees
    # cannot obtain a Hub browser session or reach another tenant's portal.
    denied = requests.post(
        s.hub + "/api/auth/login", json={"email": email, "password": password},
        headers={"X-DACOT-Tab-Session": "f0c48c10-0c47-4f2c-940c-2f229780bf66"}, timeout=10,
    )
    assert denied.status_code == 401
    assert s.call("GET", f"/hub/tenants/{other['tid']}/users", headers=owner["headers"]).status_code == 403


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


def test_portal_owner_can_change_operational_account_lifecycle_without_granting_portal_access(services):
    s, owner = services, services.restaurant()
    email = "complete-lifecycle@example.com"
    created = s.call("POST", "/portal/users", headers=owner["headers"], json={
        "name": "Usuário Inicial", "email": email, "role": "waiter",
    })
    created.raise_for_status()
    uid = created.json()["id"]
    original_password = created.json()["temp_password"]
    grant_orders_access(s, owner["tid"], uid)

    edited = s.call("PATCH", f"/portal/users/{uid}", headers=owner["headers"], json={
        "name": "Usuário Editado", "email": email, "role": "manager",
    })
    assert edited.status_code == 200
    assert edited.json()["name"] == "Usuário Editado"
    assert edited.json()["role"] == "manager"
    assert requests.post(s.hub + "/api/auth/login", json={"email": email, "password": original_password},
                         headers={"X-DACOT-Tab-Session": "de36e42e-7a7f-4d0e-a1f0-0da95d37f027"}, timeout=10).status_code == 401

    disabled = s.call("PATCH", f"/portal/users/{uid}", headers=owner["headers"],
                      json={"status": "inactive"})
    assert disabled.status_code == 200 and disabled.json()["status"] == "inactive"

    enabled = s.call("PATCH", f"/portal/users/{uid}", headers=owner["headers"],
                     json={"status": "active"})
    assert enabled.status_code == 200 and enabled.json()["status"] == "active"

    reset = s.call("POST", f"/portal/users/{uid}/reset-password", headers=owner["headers"])
    assert reset.status_code == 200
    new_password = reset.json()["temp_password"]
    stored = s.db.tenant_users.find_one({"_id": ObjectId(uid)})
    assert stored["password_hash"] != new_password
    assert bcrypt.checkpw(new_password.encode(), stored["password_hash"].encode())
    assert requests.post(s.hub + "/api/auth/login", json={"email": email, "password": original_password}, timeout=10).status_code == 401
    assert requests.post(s.hub + "/api/auth/login", json={"email": email, "password": new_password},
                         headers={"X-DACOT-Tab-Session": "5d17ae8f-28c5-409a-94e1-b4fb00a19f20"}, timeout=10).status_code == 401


def test_last_admin_and_concurrent_duplicate_guards(services):
    s, owner = services, services.restaurant()
    only_admin = s.call("PATCH", f"/hub/tenants/{owner['tid']}/users/{owner['uid']}",
                        json={"status": "inactive"})
    assert only_admin.status_code == 409

    second = s.call("POST", "/portal/users", headers=owner["headers"], json={
        "name": "Segundo Admin", "email": "second-admin@example.com", "role": "admin",
    })
    second.raise_for_status()
    assert requests.post(
        s.hub + "/api/auth/login", json={"email": "second-admin@example.com", "password": second.json()["temp_password"]},
        headers={"X-DACOT-Tab-Session": "e8cf25f7-7d01-4c23-a5ab-a6c4ae5de661"}, timeout=10,
    ).status_code == 401

    def demote(headers, uid):
        return s.call("PATCH", f"/hub/tenants/{owner['tid']}/users/{uid}", headers=headers, json={"role": "manager"})

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda args: demote(*args), [
            (s.staff, second.json()["id"]), (s.staff, owner["uid"]),
        ]))
    assert sum(r.status_code == 200 for r in results) == 1
    assert s.db.tenant_users.count_documents(
        {"tenant_id": owner["tid"], "status": "active", "role": "admin"}) == 1

    duplicate_email = "concurrent-duplicate@example.com"
    payload = {"name": "Concorrente", "email": duplicate_email, "role": "waiter"}
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(
            lambda _: s.call("POST", "/portal/users", headers=owner["headers"], json=payload), range(2)))
    assert sorted(r.status_code for r in results) == [200, 409]
