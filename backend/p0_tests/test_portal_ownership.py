"""Explicit tenant portal ownership is never inferred from an operational role."""

import secrets
import uuid

import requests
from bson import ObjectId


def _login_response(service, email):
    return requests.post(
        service.hub + "/api/auth/login",
        json={"email": email, "password": service.password},
        headers={"X-DACOT-Tab-Session": str(uuid.uuid4())},
        timeout=10,
    )


def test_legacy_tenant_needs_explicit_owner_and_operational_admin_is_not_portal_owner(services):
    tag = secrets.token_hex(6)
    tenant = services.call("POST", "/hub/tenants", json={
        "name": tag, "owner_name": "Responsável", "email": f"{tag}@example.com", "status": "active",
    })
    tenant.raise_for_status()
    tid = tenant.json()["id"]
    first_email = f"owner-{tag}@example.com"
    first = services.call("POST", f"/hub/tenants/{tid}/users", json={
        "name": "Admin operacional", "email": first_email, "role": "admin", "password": services.password,
    })
    first.raise_for_status()

    # Existing tenants must fail closed until a DACOT super-admin explicitly
    # assigns the portal owner; role="admin" is never an implicit migration.
    assert _login_response(services, first_email).status_code == 401

    assigned = services.call("PUT", f"/hub/tenants/{tid}/portal-owner", json={"user_id": first.json()["id"]})
    assert assigned.status_code == 200, assigned.text
    owner_headers = services.login(first_email, services.password)
    assert services.call("GET", "/portal/context", headers=owner_headers).status_code == 200

    second_email = f"second-{tag}@example.com"
    second = services.call("POST", f"/hub/tenants/{tid}/users", json={
        "name": "Outro admin operacional", "email": second_email, "role": "admin", "password": services.password,
    })
    second.raise_for_status()
    assert _login_response(services, second_email).status_code == 401


def test_owner_assignment_is_tenant_scoped_and_audited(services):
    first, second = services.restaurant(), services.restaurant()
    cross_tenant = services.call(
        "PUT", f"/hub/tenants/{first['tid']}/portal-owner", json={"user_id": second["uid"]},
    )
    assert cross_tenant.status_code == 404
    assert services.db.tenants.find_one({"_id": ObjectId(first["tid"])}).get("portal_owner_user_id") == first["uid"]

    audit = services.db.activity_log.find_one({"action": "tenant.portal_owner_assigned", "tenant_id": first["tid"]})
    assert audit and audit["metadata"]["owner_user_id"] == first["uid"]


def test_only_dacot_super_admin_can_assign_portal_owner(services):
    tenant = services.restaurant()
    email = f"viewer-{secrets.token_hex(6)}@example.com"
    created = services.call("POST", "/hub/users", json={
        "name": "Leitura", "email": email, "role": "viewer", "password": services.password,
    })
    created.raise_for_status()
    viewer = services.login(email, services.password)
    denied = services.call(
        "PUT", f"/hub/tenants/{tenant['tid']}/portal-owner", headers=viewer,
        json={"user_id": tenant["uid"]},
    )
    assert denied.status_code == 403
