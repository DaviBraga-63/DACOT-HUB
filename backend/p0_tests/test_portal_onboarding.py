"""P0 coverage for the optional first client access and client portal boundary."""

import secrets

from bson import ObjectId
import requests


def _onboard_payload(tag, **extra):
    return {
        "name": f"Restaurante {tag}",
        "owner_name": "Responsável inicial",
        "email": f"owner-{tag}@example.com",
        "status": "trial",
        **extra,
    }


def test_staff_onboarding_always_creates_and_links_the_initial_portal_owner(services):
    service = services
    tag = secrets.token_hex(5)
    email = f"manager-{tag}@example.com"
    with_access = service.call("POST", "/hub/tenants/onboard", json=_onboard_payload(
        tag, access_name="Gerente inicial", access_email=email,
    ))
    assert with_access.status_code == 200, with_access.text
    body = with_access.json()
    assert body["initial_access_created"] is True
    assert body["users_count"] == 1
    assert body["invitation"] == "email_sent"
    assert "temp_password" not in with_access.text

    manager = service.db.tenant_users.find_one({"tenant_id": body["id"], "email": email})
    assert manager and manager["role"] == "manager"
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


def test_email_delivery_failure_keeps_one_recoverable_owner_without_reporting_success(services):
    service = services
    tag = secrets.token_hex(5)
    email = f"email-failure-{tag}@example.com"
    previous = service.env.get("DACOT_LOCAL_INTEGRATION")
    service.env["DACOT_LOCAL_INTEGRATION"] = "0"
    try:
        service.restart_hub()
        response = service.call("POST", "/hub/tenants/onboard", json=_onboard_payload(tag, access_email=email))
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["invitation"] == "email_delivery_failed"
        owner = service.db.tenant_users.find_one({"tenant_id": body["id"], "email": email})
        tenant = service.db.tenants.find_one({"_id": ObjectId(body["id"])})
        assert owner and tenant["portal_owner_user_id"] == str(owner["_id"])
        assert owner["password_reset_required"] is True
        assert service.db.password_reset_tokens.count_documents({"user_id": str(owner["_id"]), "used": False}) == 1
        duplicate = service.call("POST", "/hub/tenants/onboard", json=_onboard_payload(
            secrets.token_hex(5), access_email=email,
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
        secrets.token_hex(5), access_email=existing_email,
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
