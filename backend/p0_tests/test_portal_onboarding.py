"""P0 coverage for the optional first client access and client portal boundary."""

import secrets

from bson import ObjectId


def _onboard_payload(tag, **extra):
    return {
        "name": f"Restaurante {tag}",
        "owner_name": "Responsável inicial",
        "email": f"owner-{tag}@example.com",
        "status": "trial",
        **extra,
    }


def test_staff_can_onboard_tenant_without_or_with_initial_manager_access(services):
    service = services
    no_access = service.call("POST", "/hub/tenants/onboard", json=_onboard_payload(secrets.token_hex(5)))
    assert no_access.status_code == 200, no_access.text
    no_access_body = no_access.json()
    assert no_access_body["initial_access_created"] is False
    assert no_access_body["users_count"] == 0
    assert service.db.tenant_users.count_documents({"tenant_id": no_access_body["id"]}) == 0

    tag = secrets.token_hex(5)
    email = f"manager-{tag}@example.com"
    with_access = service.call("POST", "/hub/tenants/onboard", json=_onboard_payload(
        tag, create_hub_access=True, access_name="Gerente inicial", access_email=email,
    ))
    assert with_access.status_code == 200, with_access.text
    body = with_access.json()
    assert body["initial_access_created"] is True
    assert body["users_count"] == 1
    assert "temp_password" not in with_access.text

    manager = service.db.tenant_users.find_one({"tenant_id": body["id"], "email": email})
    assert manager and manager["role"] == "manager"
    assert manager["user_type"] == "restaurant"
    assert manager["password_reset_required"] is True
    assert service.db.password_reset_tokens.count_documents({"user_id": str(manager["_id"]), "used": False}) == 1
    # Onboarding never activates a product or assumes an individual grant.
    assert service.db.tenant_modules.count_documents({"tenant_id": body["id"]}) == 0
    assert service.db.module_user_grants.count_documents({"tenant_id": body["id"]}) == 0


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
        secrets.token_hex(5), create_hub_access=True, access_email=existing_email,
    ))
    assert duplicate.status_code == 409
    assert service.db.tenants.count_documents({}) == before


def test_portal_exposes_only_active_released_orders_and_manager_cannot_manage_users(services):
    service, restaurant = services, services.restaurant()
    context = service.call("GET", "/portal/context", headers=restaurant["headers"])
    assert context.status_code == 200, context.text
    assert [module["key"] for module in context.json()["modules"]] == ["orders"]

    manager_email = f"manager-{secrets.token_hex(5)}@example.com"
    manager = service.call("POST", f"/hub/tenants/{restaurant['tid']}/users", json={
        "name": "Gerente", "email": manager_email, "role": "manager", "password": service.password,
    })
    manager.raise_for_status()
    manager_headers = service.login(manager_email, service.password)
    grant = service.call(
        "PUT", f"/hub/tenants/{restaurant['tid']}/modules/orders/users/{manager.json()['id']}/access",
        json={"active": True},
    )
    assert grant.status_code == 200
    assert service.call("GET", "/portal/context", headers=manager_headers).status_code == 200
    assert service.call("GET", "/portal/users", headers=manager_headers).status_code == 403

    assert service.call("POST", f"/hub/tenants/{restaurant['tid']}/modules/orders/deactivate").status_code == 200
    inactive_context = service.call("GET", "/portal/context", headers=restaurant["headers"])
    assert inactive_context.status_code == 200
    assert inactive_context.json()["modules"] == []
    assert service.call("POST", "/portal/modules/orders/launch-token", headers=restaurant["headers"]).status_code == 400
