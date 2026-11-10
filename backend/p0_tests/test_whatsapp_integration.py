"""Hub onboarding and first access delivery integration tests using an isolated DB."""

import secrets

from bson import ObjectId


def test_onboarding_whatsapp_keeps_recovery_unbound_until_phone_confirmation(services, monkeypatch):
    monkeypatch.delenv("WHATSAPP_SERVICE_URL", raising=False)
    monkeypatch.delenv("WHATSAPP_SERVICE_SECRET", raising=False)
    tag = secrets.token_hex(6)
    email = f"whatsapp-{tag}@example.com"
    response = services.call("POST", "/hub/tenants/onboard", json={
        "name": f"WhatsApp {tag}", "owner_name": "Responsável", "email": email,
        "status": "active", "mobile_phone": "(11) 91234-5678",
        "create_hub_access": True, "access_channel": "whatsapp",
    })
    assert response.status_code == 200, response.text
    assert response.json()["invitation"] == "configuration_error"
    tid = response.json()["id"]
    tenant = services.db.tenants.find_one({"_id": ObjectId(tid)})
    user = services.db.tenant_users.find_one({"tenant_id": tid, "email": email})
    assert tenant["mobile_phone"] == "+5511912345678"
    assert tenant.get("phone_user_id") is None
    assert not user.get("phone_number") and not user.get("phone_binding_version")
    confirmation = services.db.owner_contact_confirmations.find_one({"tenant_id": tid, "owner_user_id": str(user["_id"])})
    assert confirmation and confirmation["kind"] == "whatsapp" and len(confirmation["token_hash"]) == 64
    assert services.db.password_reset_tokens.count_documents({"user_id": str(user["_id"])}) == 0
    assert "whatsapp_phone" not in tenant and "whatsapp_number" not in user
    assert "token" not in confirmation and "raw_token" not in confirmation


def test_whatsapp_onboarding_requires_mobile_phone(services):
    email = f"missing-phone-{secrets.token_hex(6)}@example.com"
    response = services.call("POST", "/hub/tenants/onboard", json={
        "name": "Missing phone", "owner_name": "Owner", "email": email,
        "status": "active", "create_hub_access": True, "access_channel": "whatsapp",
    })
    assert response.status_code == 400
    assert services.db.tenants.count_documents({"email": email}) == 0


def test_legacy_phone_fields_are_read_but_new_records_write_neutral_fields(services):
    email = f"legacy-phone-{secrets.token_hex(6)}@example.com"
    created = services.call("POST", "/hub/tenants/onboard", json={
        "name": "Legacy request compatibility", "owner_name": "Owner", "email": email,
        "status": "active", "whatsapp_phone": "11912345678", "create_hub_access": True,
        "access_channel": "email",
    })
    assert created.status_code == 200, created.text
    assert created.json()["invitation"] == "email_sent"
    tenant = services.db.tenants.find_one({"_id": ObjectId(created.json()["id"])})
    assert tenant["mobile_phone"] == "+5511912345678"
    assert "whatsapp_phone" not in tenant


def test_phone_binding_cannot_cross_tenants(services):
    first_email = f"tenant-a-{secrets.token_hex(6)}@example.com"
    second_email = f"tenant-b-{secrets.token_hex(6)}@example.com"
    first = services.call("POST", "/hub/tenants/onboard", json={
        "name": "Tenant A", "owner_name": "Owner A", "email": first_email,
        "status": "active", "create_hub_access": True,
    })
    second = services.call("POST", "/hub/tenants/onboard", json={
        "name": "Tenant B", "owner_name": "Owner B", "email": second_email,
        "status": "active", "create_hub_access": True,
    })
    assert first.status_code == second.status_code == 200
    user = services.db.tenant_users.find_one({"tenant_id": first.json()["id"], "email": first_email})
    response = services.call("PUT", f"/hub/tenants/{second.json()['id']}/phone", json={
        "user_id": str(user["_id"]), "phone": "11912345678",
    })
    assert response.status_code == 404


def test_failed_whatsapp_delivery_does_not_rollback_tenant(services, monkeypatch):
    monkeypatch.delenv("WHATSAPP_SERVICE_URL", raising=False)
    monkeypatch.delenv("WHATSAPP_SERVICE_SECRET", raising=False)
    email = f"delivery-failure-{secrets.token_hex(6)}@example.com"
    response = services.call("POST", "/hub/tenants/onboard", json={
        "name": "Delivery failure", "owner_name": "Owner", "email": email,
        "status": "active", "mobile_phone": "11912345678", "create_hub_access": True,
        "access_channel": "whatsapp",
    })
    assert response.status_code == 200, response.text
    assert response.json()["invitation"] == "configuration_error"
    assert services.db.tenants.find_one({"email": email})
