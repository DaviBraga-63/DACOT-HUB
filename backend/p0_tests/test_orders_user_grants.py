"""P0 coverage for the explicit, tenant-scoped Pedidos access grants."""

import secrets

import jwt
from bson import ObjectId


def _create_restaurant_user(services, tenant_id):
    email = f"orders-grant-{secrets.token_hex(6)}@example.com"
    response = services.call("POST", f"/hub/tenants/{tenant_id}/users", json={
        "name": "Access Grant QA", "email": email, "role": "waiter",
        "password": services.password,
    })
    response.raise_for_status()
    return response.json(), services.login(email, services.password)


def test_orders_grant_is_required_and_revocation_takes_effect(services):
    service, restaurant = services, services.restaurant()
    created, headers = _create_restaurant_user(service, restaurant["tid"])
    launch_path = "/portal/modules/orders/launch-token"

    # Creating a user after the one-time migration never implicitly grants access.
    assert service.call("POST", launch_path, headers=headers).status_code == 403

    grant_path = (
        f"/hub/tenants/{restaurant['tid']}/modules/orders/users/{created['id']}/access"
    )
    assert service.call("PUT", grant_path, json={"active": True}).status_code == 200
    assert service.call("POST", launch_path, headers=headers).status_code == 200

    # An explicit revocation is durable and immediately blocks a new handoff.
    assert service.call("PUT", grant_path, json={"active": False}).status_code == 200
    assert service.call("POST", launch_path, headers=headers).status_code == 403


def test_orders_grants_are_tenant_scoped_and_staff_write_protected(services):
    service, first, second = services, services.restaurant(), services.restaurant()
    foreign_path = (
        f"/hub/tenants/{second['tid']}/modules/orders/users/{first['uid']}/access"
    )
    assert service.call("PUT", foreign_path, json={"active": True}).status_code == 404

    viewer_email = f"orders-viewer-{secrets.token_hex(6)}@example.com"
    created = service.call("POST", "/hub/users", json={
        "name": "Orders viewer", "email": viewer_email, "role": "viewer",
        "password": service.password,
    })
    created.raise_for_status()
    viewer_headers = service.login(viewer_email, service.password)
    list_path = f"/hub/tenants/{first['tid']}/modules/orders/access-grants"
    assert service.call("GET", list_path, headers=viewer_headers).status_code == 200
    own_path = f"/hub/tenants/{first['tid']}/modules/orders/users/{first['uid']}/access"
    assert service.call("PUT", own_path, json={"active": False}, headers=viewer_headers).status_code == 403


def test_orders_template_requires_single_slug_and_authorized_origin(services):
    service = services
    endpoint = "/hub/modules/orders/launch-url-template"
    assert service.call("PATCH", endpoint, json={
        "launch_url_template": "https://orders.example.test/{slug}/{slug}",
    }).status_code == 400
    assert service.call("PATCH", endpoint, json={
        "launch_url_template": "https://untrusted.example.test/{slug}",
    }).status_code == 400
    accepted = service.call("PATCH", endpoint, json={
        "launch_url_template": "https://orders.example.test/{slug}",
    })
    assert accepted.status_code == 200
    assert accepted.json()["launch_url_template"] == "https://orders.example.test/{slug}"


def test_public_revalidation_denies_a_revoked_orders_grant(services):
    service, restaurant = services, services.restaurant()
    handoff = service.handoff(restaurant)
    claims = jwt.decode(handoff, service.secret, algorithms=["HS256"], audience="dacot-orders")
    payload = {"subject": claims["sub"], "role": claims["role"], "hub_access": claims["hub_access"]}
    access_path = f"/public/tenants/{restaurant['tid']}/modules/orders/access"
    assert service.call("POST", access_path, headers={"X-Module-Key": service.key}, json=payload).json()["active"] is True

    grant_path = f"/hub/tenants/{restaurant['tid']}/modules/orders/users/{restaurant['uid']}/access"
    assert service.call("PUT", grant_path, json={"active": False}).status_code == 200
    assert service.call("POST", access_path, headers={"X-Module-Key": service.key}, json=payload).json()["active"] is False


def test_grant_does_not_bypass_an_invalid_handoff_role(services):
    service, restaurant = services, services.restaurant()
    # Simulates a legacy/corrupt persisted role: the active grant is not authority by itself.
    service.db.tenant_users.update_one({"_id": ObjectId(restaurant["uid"])}, {"$set": {"role": "owner"}})
    assert service.call("POST", "/portal/modules/orders/launch-token", headers=restaurant["headers"]).status_code == 403


def test_orders_template_http_is_rejected_by_endpoint_in_production(services):
    service = services
    original_env = service.env.copy()
    try:
        service.env["APP_ENV"] = "production"
        service.env["HANDOFF_ALLOWED_ORIGINS_JSON"] = (
            '{"orders":["https://orders.example.test","https://dacot-pedidos-frontend.onrender.com"]}'
        )
        service.restart_hub()
        response = service.call("PATCH", "/hub/modules/orders/launch-url-template", json={
            "launch_url_template": "http://orders.example.test/{slug}",
        })
        assert response.status_code == 400
    finally:
        service.env.clear()
        service.env.update(original_env)
        service.restart_hub()
