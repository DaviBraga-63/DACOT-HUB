"""Focused P0 coverage for owner-managed Pedidos identities."""
from bson import ObjectId
import requests
from uuid import uuid4
from backend.auth_sessions import new_browser_binding, session_query


def _grant(services, tenant_id, user_id):
    return services.db.module_user_grants.find_one({
        "tenant_id": tenant_id, "user_id": user_id, "module_key": "orders",
    })


def _custom_role(services, tenant_id, role_id="leader-role"):
    services.odb.custom_roles.insert_one({
        "id": role_id,
        "restaurant_id": tenant_id,
        "name": "Garçom líder",
        "name_key": "garçom líder",
        "permissions": ["orders.view"],
    })
    return role_id


def _live_session(services, user_id):
    query = session_query(new_browser_binding(), str(uuid4()))
    services.db.auth_sessions.insert_one({
        **query, "user_id": user_id, "user_type": "restaurant", "revoked_at": None,
    })
    return query


def test_portal_owner_only_and_tenant_isolation(services):
    owner, other = services.restaurant(), services.restaurant()
    assert services.call("GET", "/portal/users", headers=owner["headers"]).status_code == 200

    # An operational admin is intentionally not eligible for a HUB portal session.
    second = services.call(
        "POST", f"/hub/tenants/{owner['tid']}/users",
        json={"name": "Admin", "email": "ops-admin@example.com", "role": "admin", "password": services.password},
    )
    second.raise_for_status()
    assert requests.post(
        services.hub + "/api/auth/login",
        json={"email": "ops-admin@example.com", "password": services.password},
        headers={"X-DACOT-Tab-Session": str(uuid4())}, timeout=10,
    ).status_code == 401
    assert services.call(
        "PATCH", f"/portal/users/{other['uid']}", headers=owner["headers"], json={"name": "x"},
    ).status_code == 404


def test_custom_role_operations_hold_grant_until_the_role_is_validated(services):
    owner = services.restaurant()
    created = services.call(
        "POST", "/portal/users", headers=owner["headers"],
        json={"name": "Garçom", "email": "custom-role@example.com", "role": "waiter",
              "password": services.password, "custom_role_id": "missing-role"},
    )
    assert created.status_code == 503
    record = services.db.tenant_users.find_one({"email": "custom-role@example.com"})
    assert record and _grant(services, owner["tid"], str(record["_id"]))["active"] is False
    assert services.odb.users.count_documents(
        {"restaurant_id": owner["tid"], "hub_user_id": str(record["_id"])}
    ) == 1

    # Retrying after the role becomes valid reuses the same operational mirror.
    role_id = _custom_role(services, owner["tid"])
    retry = services.call(
        "PUT", f"/portal/users/{record['_id']}/custom-role", headers=owner["headers"],
        json={"custom_role_id": role_id},
    )
    assert retry.status_code == 200
    assert _grant(services, owner["tid"], str(record["_id"]))["active"] is True
    assert services.odb.users.count_documents(
        {"restaurant_id": owner["tid"], "hub_user_id": str(record["_id"])}
    ) == 1

    # A failed change never leaves the user with default waiter access.
    failed_change = services.call(
        "PATCH", f"/portal/users/{record['_id']}", headers=owner["headers"],
        json={"custom_role_id": "other-missing-role"},
    )
    assert failed_change.status_code == 503
    assert _grant(services, owner["tid"], str(record["_id"]))["active"] is False


def test_password_reset_and_custom_role_reactivation_fail_closed(services):
    owner = services.restaurant()
    role_id = _custom_role(services, owner["tid"], "reactivation-role")
    created = services.call(
        "POST", "/portal/users", headers=owner["headers"],
        json={"name": "Atendente", "email": "reactivate@example.com", "role": "waiter",
              "password": services.password, "custom_role_id": role_id},
    )
    created.raise_for_status()
    uid = created.json()["id"]
    _live_session(services, uid)

    assert services.call("PATCH", f"/portal/users/{uid}", headers=owner["headers"], json={"status": "inactive"}).status_code == 200
    assert _grant(services, owner["tid"], uid)["active"] is False
    services.stop("orders")
    try:
        assert services.call("PATCH", f"/portal/users/{uid}", headers=owner["headers"], json={"status": "active"}).status_code == 503
        assert _grant(services, owner["tid"], uid)["active"] is False
    finally:
        services.restart_orders()
    assert services.call("PATCH", f"/portal/users/{uid}", headers=owner["headers"], json={"status": "active"}).status_code == 200
    assert _grant(services, owner["tid"], uid)["active"] is True

    # This session is still live at the time of the password reset and must
    # therefore receive the password-reset revocation reason.
    session_query_filter = _live_session(services, uid)
    before = services.db.tenant_users.find_one({"_id": ObjectId(uid)})["token_version"]
    assert services.call(
        "POST", f"/portal/users/{uid}/password", headers=owner["headers"],
        json={"password": "new-password-safe"},
    ).status_code == 200
    assert services.db.tenant_users.find_one({"_id": ObjectId(uid)})["token_version"] == before + 1
    session = services.db.auth_sessions.find_one(session_query_filter)
    assert session["revoked_at"] is not None and session["revocation_reason"] == "password_reset"
