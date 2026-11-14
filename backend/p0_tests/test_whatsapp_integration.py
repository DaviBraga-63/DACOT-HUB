"""Hub onboarding and first access delivery integration tests using an isolated DB."""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from pymongo.errors import DuplicateKeyError


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


def test_pending_owner_transfer_completes_only_after_confirmation_and_first_access(services):
    """Exercise the new transfer boundary with the real Hub process and MongoDB."""
    current = services.restaurant()
    tid, previous_id = current["tid"], current["uid"]
    previous = services.db.tenant_users.find_one({"_id": ObjectId(previous_id)})
    services.db.tenant_users.update_one({"_id": previous["_id"]}, {"$set": {
        "phone_number": "+5511912345678", "phone_binding_version": "old-binding",
    }})
    services.db.tenants.update_one({"_id": ObjectId(tid)}, {"$set": {
        "mobile_phone": "+5511912345678", "phone_user_id": previous_id,
    }})

    new_id = ObjectId()
    new_email = f"incoming-{secrets.token_hex(6)}@example.com"
    services.db.tenant_users.insert_one({
        "_id": new_id, "tenant_id": tid, "name": "Nova Responsável", "email": new_email,
        "role": "manager", "status": "active", "user_type": "restaurant",
        "password_hash": "not-a-valid-password", "password_reset_required": True,
        "token_version": 0, "pending_owner_transfer": True,
    })
    transfer_id = services.db.owner_transfers.insert_one({
        "tenant_id": tid, "previous_owner_user_id": previous_id, "new_owner_user_id": str(new_id),
        "state": "pending", "created_at": datetime.now(timezone.utc),
    }).inserted_id
    raw_confirmation = secrets.token_urlsafe(32)
    services.db.owner_contact_confirmations.insert_one({
        "token_hash": hashlib.sha256(raw_confirmation.encode()).hexdigest(), "tenant_id": tid,
        "owner_user_id": str(new_id), "kind": "whatsapp", "proposed_value": "+5511988888888",
        "used": False, "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
        "created_at": datetime.now(timezone.utc), "first_access": True,
        "owner_transfer_id": str(transfer_id), "requested_by": "test",
    })

    confirmed = services.call("POST", "/auth/confirm-owner-whatsapp", headers={}, json={"token": raw_confirmation})
    assert confirmed.status_code == 200, confirmed.text
    continuation = confirmed.json()["continuation_token"]
    assert confirmed.json()["first_access_required"] is True
    assert services.db.tenants.find_one({"_id": ObjectId(tid)})["portal_owner_user_id"] == previous_id
    assert services.db.password_reset_tokens.find_one({"token_hash": hashlib.sha256(continuation.encode()).hexdigest(), "used": False})
    assert services.call("GET", "/portal/context", headers=current["headers"]).status_code == 200

    reset = services.call("POST", "/auth/reset-password", headers={}, json={"token": continuation, "password": "new-owner-password"})
    assert reset.status_code == 200, reset.text
    tenant = services.db.tenants.find_one({"_id": ObjectId(tid)})
    assert tenant["portal_owner_user_id"] == str(new_id)
    assert tenant["phone_user_id"] == str(new_id)
    assert services.db.owner_transfers.find_one({"_id": transfer_id})["state"] == "completed"
    assert services.db.tenant_users.find_one({"_id": ObjectId(previous_id)}) is not None
    assert services.call("GET", "/portal/context", headers=current["headers"]).status_code == 401
    new_headers = services.login(new_email, "new-owner-password")
    assert services.call("GET", "/portal/context", headers=new_headers).status_code == 200
    assert services.call("POST", "/auth/reset-password", headers={}, json={"token": continuation, "password": "other-password"}).status_code == 400


def test_cancelled_owner_transfer_keeps_current_owner_and_unique_pending_index(services):
    current = services.restaurant()
    tid, previous_id = current["tid"], current["uid"]
    incoming_id = ObjectId()
    services.db.tenant_users.insert_one({
        "_id": incoming_id, "tenant_id": tid, "name": "Pendente", "email": f"pending-{secrets.token_hex(6)}@example.com",
        "role": "manager", "status": "active", "user_type": "restaurant", "password_hash": "synthetic",
        "password_reset_required": True, "token_version": 0, "pending_owner_transfer": True,
    })
    transfer_id = services.db.owner_transfers.insert_one({
        "tenant_id": tid, "previous_owner_user_id": previous_id, "new_owner_user_id": str(incoming_id),
        "state": "pending", "created_at": datetime.now(timezone.utc),
    }).inserted_id
    try:
        services.db.owner_transfers.insert_one({
            "tenant_id": tid, "previous_owner_user_id": previous_id, "new_owner_user_id": str(ObjectId()),
            "state": "pending", "created_at": datetime.now(timezone.utc),
        })
        assert False, "the partial unique index must reject concurrent pending transfers"
    except DuplicateKeyError:
        pass
    cancelled = services.call("DELETE", f"/hub/tenants/{tid}/owner-transfer/{transfer_id}")
    assert cancelled.status_code == 200, cancelled.text
    assert services.db.tenants.find_one({"_id": ObjectId(tid)})["portal_owner_user_id"] == previous_id
    assert services.db.owner_transfers.find_one({"_id": transfer_id})["state"] == "cancelled"
    assert services.db.tenant_users.find_one({"_id": incoming_id})["status"] == "inactive"


def test_owner_name_update_changes_no_identity_or_credentials(services):
    current = services.restaurant()
    tid, owner_id = current["tid"], ObjectId(current["uid"])
    before = services.db.tenant_users.find_one({"_id": owner_id})
    updated = services.call("PATCH", f"/hub/tenants/{tid}/owner-name", json={"name": "Nome Corrigido"})
    assert updated.status_code == 200, updated.text
    after = services.db.tenant_users.find_one({"_id": owner_id})
    tenant = services.db.tenants.find_one({"_id": ObjectId(tid)})
    assert after["name"] == tenant["owner_name"] == "Nome Corrigido"
    assert after["email"] == before["email"]
    assert after["password_hash"] == before["password_hash"]
    assert after["role"] == before["role"]
    assert services.call("GET", "/portal/context", headers=current["headers"]).status_code == 200
