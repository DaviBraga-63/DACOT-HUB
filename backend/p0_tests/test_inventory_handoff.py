"""Inventory handoff rollout and authorization contract tests."""
import time

import jwt
import pytest
import requests


@pytest.fixture(scope="module")
def inventory_services(services):
    services.env["INVENTORY_MODULE_ENABLED"] = "true"
    services.env["HANDOFF_ALLOWED_ORIGINS_JSON"] = (
        '{"orders":["https://orders.example.test"],'
        '"inventory":["https://estoque.dacot.com.br"]}'
    )
    services.restart_hub()
    try:
        yield services
    finally:
        services.env["INVENTORY_MODULE_ENABLED"] = "false"
        services.env["HANDOFF_ALLOWED_ORIGINS_JSON"] = (
            '{"orders":["https://orders.example.test"]}'
        )
        services.restart_hub()


def _activate_inventory(services, identity):
    result = services.call(
        "POST", f"/hub/tenants/{identity['tid']}/modules/inventory/activate",
    )
    assert result.status_code == 200, result.text


def _inventory_handoff(services, identity):
    result = services.call(
        "POST", "/portal/modules/inventory/launch-token",
        headers=identity["headers"],
    )
    return result


def test_inventory_handoff_uses_canonical_contract_and_independent_service_key(inventory_services):
    services = inventory_services
    identity = services.restaurant()
    _activate_inventory(services, identity)

    result = _inventory_handoff(services, identity)
    assert result.status_code == 200, result.text
    data = result.json()
    claims = jwt.decode(
        data["handoff"], services.secret, algorithms=["HS256"],
        audience="dacot-estoque", issuer="dacot-hub",
    )
    assert data["launch_url"] == "https://estoque.dacot.com.br"
    assert data["expires_in"] == 60
    assert claims["module"] == "inventory"
    assert claims["aud"] == "dacot-estoque"
    assert claims["restaurant_id"] == identity["tid"]
    assert claims["sub"] == f"tenant_user:{identity['uid']}"
    assert claims["role"] == "manager"
    assert set(claims["hub_access"]) == {"user", "tenant", "module"}
    assert claims["exp"] - claims["iat"] == 60

    status = requests.get(
        f"{services.hub}/api/public/tenants/{identity['tid']}/modules/inventory/status",
        headers={"X-Module-Key": services.inventory_key}, timeout=5,
    )
    assert status.status_code == 200 and status.json()["active"] is True
    assert requests.get(
        f"{services.hub}/api/public/tenants/{identity['tid']}/modules/inventory/status",
        headers={"X-Module-Key": services.key}, timeout=5,
    ).status_code == 401


def test_inventory_unactivated_restaurant_cannot_receive_handoff(inventory_services):
    services = inventory_services
    identity = services.restaurant()
    result = _inventory_handoff(services, identity)
    assert result.status_code == 400


def test_inventory_global_rollout_gate_defaults_closed_and_needs_manual_activation(inventory_services):
    services = inventory_services
    identity = services.restaurant()
    services.env["INVENTORY_MODULE_ENABLED"] = "false"
    services.restart_hub()
    try:
        status = requests.get(
            f"{services.hub}/api/public/tenants/{identity['tid']}/modules/inventory/status",
            headers={"X-Module-Key": services.inventory_key}, timeout=5,
        )
        assert status.status_code == 200 and status.json() == {
            "active": False, "module": "inventory",
        }
        assert services.call(
            "POST", f"/hub/tenants/{identity['tid']}/modules/inventory/activate",
        ).status_code == 400
        assert _inventory_handoff(services, identity).status_code == 400
    finally:
        services.env["INVENTORY_MODULE_ENABLED"] = "true"
        services.restart_hub()


def test_inventory_rejects_unauthorized_role(inventory_services):
    services = inventory_services
    identity = services.restaurant()
    _activate_inventory(services, identity)
    services.db.tenant_users.update_one(
        {"_id": __import__("bson").ObjectId(identity["uid"])},
        {"$set": {"role": "waiter"}},
    )
    result = _inventory_handoff(services, identity)
    assert result.status_code == 403


def test_inventory_revocation_and_tenant_isolation_are_authoritative(inventory_services):
    services = inventory_services
    restaurant_a = services.restaurant()
    restaurant_b = services.restaurant()
    _activate_inventory(services, restaurant_a)
    _activate_inventory(services, restaurant_b)
    handoff = _inventory_handoff(services, restaurant_a).json()["handoff"]
    claims = jwt.decode(
        handoff, services.secret, algorithms=["HS256"],
        audience="dacot-estoque", issuer="dacot-hub",
    )
    path = f"/public/tenants/{restaurant_b['tid']}/modules/inventory/access"
    cross_tenant = services.call(
        "POST", path, headers={"X-Module-Key": services.inventory_key},
        json={"subject": claims["sub"], "role": claims["role"],
              "hub_access": claims["hub_access"]},
    )
    assert cross_tenant.status_code == 200
    assert cross_tenant.json() == {"active": False}

    services.call(
        "POST", f"/hub/tenants/{restaurant_a['tid']}/modules/inventory/deactivate",
    ).raise_for_status()
    revoked = services.call(
        "POST", f"/public/tenants/{restaurant_a['tid']}/modules/inventory/access",
        headers={"X-Module-Key": services.inventory_key},
        json={"subject": claims["sub"], "role": claims["role"],
              "hub_access": claims["hub_access"]},
    )
    assert revoked.status_code == 200 and revoked.json() == {"active": False}


def test_pedidos_rejects_inventory_and_expired_handoff_tokens(inventory_services):
    services = inventory_services
    identity = services.restaurant()
    _activate_inventory(services, identity)
    inventory = _inventory_handoff(services, identity).json()["handoff"]
    assert services.exchange(inventory).status_code == 401

    now = int(time.time())
    expired = jwt.encode({
        "iss": "dacot-hub", "aud": "dacot-orders",
        "sub": f"tenant_user:{identity['uid']}",
        "restaurant_id": identity["tid"], "role": "admin", "module": "orders",
        "hub_access": {"user": 0, "tenant": 0, "module": 0},
        "jti": "expired-inventory-contract-test", "iat": now - 120,
        "nbf": now - 120, "exp": now - 60, "handoff_version": 1,
    }, services.secret, algorithm="HS256")
    assert services.exchange(expired).status_code == 401
