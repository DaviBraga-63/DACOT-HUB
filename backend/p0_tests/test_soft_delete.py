"""P0 coverage for non-destructive removal of tenants and Hub staff."""

import secrets

import requests
import jwt
import pytest
from bson import ObjectId


def _create_staff(services, *, role="admin"):
    tag = secrets.token_hex(6)
    response = services.call(
        "POST", "/hub/users",
        json={"name": f"Staff {tag}", "email": f"staff-{tag}@example.com", "role": role, "password": services.password},
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("deleted_value", ["missing", "null"])
def test_legacy_empty_fields_keep_access_and_still_revoke(services, deleted_value):
    """Only disposable P0 records are changed; deleted identities must stay revoked."""
    restaurant = services.restaurant()
    tenant_id, user_id = restaurant["tid"], restaurant["uid"]
    operator = "$unset" if deleted_value == "missing" else "$set"
    empty_value = "" if deleted_value == "missing" else None
    tenant_update = {operator: {"deleted_at": empty_value}}
    tenant_update.setdefault("$unset", {})["access_version"] = ""
    user_update = {operator: {"deleted_at": empty_value}}
    user_update.setdefault("$unset", {})["token_version"] = ""
    services.db.tenants.update_one(
        {"_id": ObjectId(tenant_id)},
        tenant_update,
    )
    services.db.tenant_users.update_one(
        {"_id": ObjectId(user_id)},
        user_update,
    )
    services.db.tenant_modules.update_one(
        {"tenant_id": tenant_id, "module_key": "orders"},
        {"$unset": {"access_version": ""}},
    )

    assert services.call("GET", f"/hub/tenants/{tenant_id}").status_code == 200
    assert services.call("GET", "/portal/context", headers=restaurant["headers"]).status_code == 200
    token = services.exchange(services.handoff(restaurant))
    assert token.status_code == 200, token.text
    assert services.call("DELETE", f"/hub/tenants/{tenant_id}").status_code == 200
    assert services.call("GET", "/portal/context", headers=restaurant["headers"]).status_code == 401
    assert services.order_me(token.json()["token"]).status_code == 403
    assert services.db.tenants.find_one({"_id": ObjectId(tenant_id)})["deleted_at"]
    assert services.db.tenant_users.find_one({"_id": ObjectId(user_id)})


@pytest.mark.parametrize("bad_version", [None, -1, "invalid", True])
@pytest.mark.parametrize("target", ["user", "tenant", "module"])
def test_invalid_security_versions_fail_closed_and_preserve_records(services, target, bad_version):
    restaurant = services.restaurant()
    tenant_id, user_id = restaurant["tid"], restaurant["uid"]
    orders_token = services.exchange(services.handoff(restaurant)).json()["token"]
    if target == "user":
        collection, query, field = services.db.tenant_users, {"_id": ObjectId(user_id)}, "token_version"
    elif target == "tenant":
        collection, query, field = services.db.tenants, {"_id": ObjectId(tenant_id)}, "access_version"
    else:
        collection = services.db.tenant_modules
        query, field = {"tenant_id": tenant_id, "module_key": "orders"}, "access_version"
    collection.update_one(query, {"$set": {field: bad_version}})

    if target == "user":
        assert services.call("GET", "/auth/me", headers=restaurant["headers"]).status_code == 401
        email = services.db.tenant_users.find_one({"_id": ObjectId(user_id)})["email"]
        login = requests.post(
            services.hub + "/api/auth/login", json={"email": email, "password": services.password},
            headers={"X-DACOT-Tab-Session": secrets.token_hex(16)}, timeout=10,
        )
        assert login.status_code == 401
    else:
        assert services.call("POST", "/portal/modules/orders/launch-token", headers=restaurant["headers"]).status_code == 403
    assert services.order_me(orders_token).status_code == 403
    assert services.call("DELETE", f"/hub/tenants/{tenant_id}").status_code == 200
    assert services.db.tenants.find_one({"_id": ObjectId(tenant_id)})["deleted_at"]
    assert services.db.tenant_users.find_one({"_id": ObjectId(user_id)})
    assert services.call("GET", "/auth/me", headers=restaurant["headers"]).status_code == 401


@pytest.mark.parametrize("bad_version", [None, -1, "invalid", True])
def test_invalid_staff_version_blocks_existing_and_new_sessions(services, bad_version):
    staff = _create_staff(services)
    identity = services.login(staff["email"], services.password)
    services.db.hub_users.update_one({"_id": ObjectId(staff["id"])}, {"$set": {"token_version": bad_version}})
    assert services.call("GET", "/auth/me", headers=identity).status_code == 401
    login = requests.post(
        services.hub + "/api/auth/login", json={"email": staff["email"], "password": services.password},
        headers={"X-DACOT-Tab-Session": secrets.token_hex(16)}, timeout=10,
    )
    assert login.status_code == 401
    assert services.call("DELETE", f"/hub/users/{staff['id']}").status_code == 200
    stored = services.db.hub_users.find_one({"_id": ObjectId(staff["id"])})
    assert stored["deleted_at"] and stored["token_version"] == bad_version


def test_tenant_removal_preserves_records_and_blocks_access(services):
    restaurant = services.restaurant()
    tid = restaurant["tid"]
    live_handoff = services.handoff(restaurant)
    pending_handoff = services.handoff(restaurant)
    claims = jwt.decode(live_handoff, services.secret, algorithms=["HS256"], audience="dacot-orders")
    established_session = services.exchange(live_handoff)
    assert established_session.status_code == 200, established_session.text
    orders_token = established_session.json()["token"]
    modules_before = services.db.tenant_modules.count_documents({"tenant_id": tid})
    users_before = services.db.tenant_users.count_documents({"tenant_id": tid})

    removed = services.call("DELETE", f"/hub/tenants/{tid}")
    assert removed.status_code == 200, removed.text

    tenant = services.db.tenants.find_one({"_id": ObjectId(tid)})
    assert tenant["deleted_at"] and tenant["deleted_by"] and tenant["status"] == "active"
    assert services.db.tenant_modules.count_documents({"tenant_id": tid}) == modules_before
    assert services.db.tenant_users.count_documents({"tenant_id": tid}) == users_before
    assert services.call("GET", "/hub/tenants").status_code == 200
    assert tid not in {tenant["id"] for tenant in services.call("GET", "/hub/tenants").json()}
    assert services.call("GET", f"/hub/tenants/{tid}").status_code == 404
    assert services.call("GET", f"/hub/tenants/{tid}/modules").status_code == 404
    assert requests.get(services.hub + "/api/auth/me", headers=restaurant["headers"], timeout=10).status_code == 401
    assert requests.post(
        services.hub + "/api/auth/login",
        json={"email": services.db.tenant_users.find_one({"_id": ObjectId(restaurant["uid"])})["email"],
              "password": services.password},
        headers={"X-DACOT-Tab-Session": secrets.token_hex(16)}, timeout=10,
    ).status_code == 401
    # The same centralized revalidation that Pedidos uses rejects both a
    # pre-existing handoff and the authority attached to an old module session.
    assert services.exchange(pending_handoff).status_code == 403
    # /api/auth/me is the fresh revalidation endpoint polled by the Pedidos
    # client, so an already-issued Pedidos session is also denied immediately.
    assert services.order_me(orders_token).status_code == 403
    access = services.call(
        "POST", f"/public/tenants/{tid}/modules/orders/access",
        headers={"X-Module-Key": services.key},
        json={"subject": claims["sub"], "role": claims["role"], "hub_access": claims["hub_access"]},
    )
    assert access.status_code == 200 and access.json() == {"active": False}
    activity = services.db.activity_log.find_one({"action": "tenant.deleted", "target_id": tid})
    assert activity and activity["metadata"]["soft_delete"] is True


def test_staff_removal_is_logical_and_enforces_role_protections(services):
    staff = _create_staff(services)
    identity = services.login(staff["email"], services.password)

    removed = services.call("DELETE", f"/hub/users/{staff['id']}")
    assert removed.status_code == 200, removed.text
    stored = services.db.hub_users.find_one({"email": staff["email"]})
    assert stored["deleted_at"] and stored["active"] is False
    assert services.call("GET", "/hub/users").status_code == 200
    assert staff["id"] not in {item["id"] for item in services.call("GET", "/hub/users").json()}
    assert requests.get(services.hub + "/api/auth/me", headers=identity, timeout=10).status_code == 401
    assert requests.post(
        services.hub + "/api/auth/login", json={"email": staff["email"], "password": services.password},
        headers={"X-DACOT-Tab-Session": secrets.token_hex(16)}, timeout=10,
    ).status_code == 401
    assert services.call("PATCH", f"/hub/users/{staff['id']}", json={"active": True}).status_code == 404

    initial = services.db.hub_users.find_one({"email": services.admin_email})
    assert services.call("DELETE", f"/hub/users/{initial['_id']}").status_code == 400

    regular_admin = _create_staff(services, role="admin")
    regular_identity = services.login(regular_admin["email"], services.password)
    assert services.call("DELETE", f"/hub/users/{initial['_id']}", headers=regular_identity).status_code == 403
    activity = services.db.activity_log.find_one({"action": "hub_user.deleted", "target_id": staff["id"]})
    assert activity and activity["metadata"]["soft_delete"] is True


def test_tenant_user_removal_preserves_history_and_revokes_orders_access(services):
    restaurant, other = services.restaurant(), services.restaurant()
    tag = secrets.token_hex(6)
    created = services.call(
        "POST", f"/hub/tenants/{restaurant['tid']}/users",
        json={"name": "Marco", "email": f"marco-{tag}@example.com", "role": "kitchen", "password": services.password},
    )
    assert created.status_code == 200, created.text
    tenant_user = created.json()
    uid = tenant_user["id"]
    assert services.call(
        "PUT", f"/hub/tenants/{restaurant['tid']}/modules/orders/users/{uid}/access",
        json={"active": True},
    ).status_code == 200

    user_headers = services.login(tenant_user["email"], services.password)
    identity = {"tid": restaurant["tid"], "uid": uid, "headers": user_headers}
    orders_token = services.exchange(services.handoff(identity)).json()["token"]
    pending_handoff = services.handoff(identity)
    assert services.order_me(orders_token).status_code == 200
    grant_before = services.db.module_user_grants.find_one(
        {"tenant_id": restaurant["tid"], "user_id": uid, "module_key": "orders"}
    )

    # A restaurant account is never allowed to administer another employee.
    assert services.call(
        "DELETE", f"/hub/tenants/{restaurant['tid']}/users/{uid}", headers=restaurant["headers"]
    ).status_code == 403
    # Tenant id is authoritative: a user from another restaurant cannot be removed.
    assert services.call(
        "DELETE", f"/hub/tenants/{restaurant['tid']}/users/{other['uid']}"
    ).status_code == 404

    removed = services.call("DELETE", f"/hub/tenants/{restaurant['tid']}/users/{uid}")
    assert removed.status_code == 200, removed.text
    stored = services.db.tenant_users.find_one({"_id": ObjectId(uid)})
    assert stored["deleted_at"] and stored["deleted_by"] and stored["email"] == tenant_user["email"]
    assert services.db.module_user_grants.find_one({"_id": grant_before["_id"]})

    listed = services.call("GET", f"/hub/tenants/{restaurant['tid']}/users")
    assert listed.status_code == 200
    assert uid not in {item["id"] for item in listed.json()}
    portal_list = services.call("GET", "/portal/users", headers=restaurant["headers"])
    assert portal_list.status_code == 200
    assert uid not in {item["id"] for item in portal_list.json()}
    assert services.call(
        "PATCH", f"/hub/tenants/{restaurant['tid']}/users/{uid}", json={"status": "active"}
    ).status_code == 404

    assert services.call("GET", "/portal/context", headers=user_headers).status_code == 401
    assert requests.post(
        services.hub + "/api/auth/login",
        json={"email": tenant_user["email"], "password": services.password},
        headers={"X-DACOT-Tab-Session": secrets.token_hex(16)}, timeout=10,
    ).status_code == 401
    # The frontend polls this fresh endpoint while a Pedidos/KDS page is idle.
    assert services.order_me(orders_token).status_code == 403
    assert services.exchange(pending_handoff).status_code == 403
    assert services.exchange(services.handoff(restaurant)).status_code == 200
    activity = services.db.activity_log.find_one({"action": "tenant_user.deleted", "target_id": uid})
    assert activity and activity["tenant_id"] == restaurant["tid"] and activity["metadata"]["soft_delete"] is True
