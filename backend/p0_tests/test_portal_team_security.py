"""P0 coverage for the owner-scoped, read-only portal team view."""

import requests
from uuid import uuid4


def _orders_user(services, tenant_id, *, name, role="waiter", active=True, custom_role_id=None):
    user = {
        "id": str(uuid4()), "restaurant_id": tenant_id,
        "name": name, "email": f"{uuid4().hex}@example.com", "role": role,
        "permissions": ["orders.view"], "active": active,
        "password_hash": "local-only", "created_at": "2026-01-01T00:00:00+00:00",
    }
    if custom_role_id:
        user["custom_role_id"] = custom_role_id
    services.odb.users.insert_one(user)
    return user


def test_portal_team_is_read_only_and_tenant_scoped(services):
    owner, other = services.restaurant(), services.restaurant()
    role_id = "leader-role"
    services.odb.custom_roles.insert_one({
        "id": role_id, "restaurant_id": owner["tid"], "name": "Garçom líder",
        "name_key": "garçom líder", "permissions": ["orders.view"],
    })
    visible = _orders_user(services, owner["tid"], name="Ana", custom_role_id=role_id)
    inactive = _orders_user(services, owner["tid"], name="Bruno", active=False)
    hidden = _orders_user(services, other["tid"], name="Outro restaurante")

    result = services.call("GET", "/portal/team", headers=owner["headers"])
    assert result.status_code == 200, result.text
    payload = result.json()
    assert set(payload) == {"team"}
    ana = next(member for member in payload["team"] if member["name"] == visible["name"])
    bruno = next(member for member in payload["team"] if member["name"] == inactive["name"])
    assert ana == {
        "name": "Ana", "role": "Garçom líder", "module": "Pedidos & Operação",
        "status": "active", "access": "granted",
    }
    assert bruno["status"] == "inactive" and bruno["access"] == "blocked"
    assert hidden["name"] not in result.text
    assert visible["email"] not in result.text

    # The portal no longer owns any write operation for module personnel.
    blocked_paths = [
        ("POST", "/portal/users"),
        ("PATCH", "/portal/users/507f1f77bcf86cd799439011"),
        ("POST", "/portal/users/507f1f77bcf86cd799439011/password"),
        ("PUT", "/portal/users/507f1f77bcf86cd799439011/custom-role"),
        ("PUT", "/portal/users/507f1f77bcf86cd799439011/orders/access"),
    ]
    for method, path in blocked_paths:
        assert services.call(method, path, headers=owner["headers"], json={}).status_code == 404


def test_operational_admin_cannot_access_hub_portal_and_team_fails_closed(services):
    owner = services.restaurant()
    created = services.call(
        "POST", f"/hub/tenants/{owner['tid']}/users",
        json={"name": "Admin operacional", "email": "ops-admin@example.com",
              "role": "admin", "password": services.password},
    )
    created.raise_for_status()
    denied = requests.post(
        services.hub + "/api/auth/login",
        json={"email": "ops-admin@example.com", "password": services.password},
        headers={"X-DACOT-Tab-Session": str(uuid4())}, timeout=10,
    )
    assert denied.status_code == 401

    services.stop("orders")
    try:
        assert services.call("GET", "/portal/team", headers=owner["headers"]).status_code == 503
    finally:
        services.restart_orders()
