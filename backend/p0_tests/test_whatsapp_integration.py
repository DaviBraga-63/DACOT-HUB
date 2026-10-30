"""Integration against the P0 harness: disposable localhost Mongo, never production."""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor

from bson import ObjectId


def test_onboarding_outage_binding_and_old_whatsapp_link_revocation(services):
    tag = secrets.token_hex(6)
    email = f"wa-{tag}@example.com"
    response = services.call("POST", "/hub/tenants/onboard", json={
        "name": f"WA {tag}", "owner_name": "Responsável", "email": email,
        "status": "active", "whatsapp_phone": "11912345678",
        "create_hub_access": True, "access_channel": "whatsapp",
    })
    assert response.status_code == 200, response.text
    assert response.json()["invitation"] == "unavailable"
    tid = response.json()["id"]
    user = services.db.tenant_users.find_one({"tenant_id": tid, "email": email})
    tenant = services.db.tenants.find_one({"_id": ObjectId(tid)})
    assert tenant["whatsapp_user_id"] == str(user["_id"])
    assert user["whatsapp_number"] == "+5511912345678"
    assert user["whatsapp_audit"][0]["actor_id"]

    token = secrets.token_urlsafe(32)
    services.db.password_reset_tokens.insert_one({
        "token_hash": hashlib.sha256(token.encode()).hexdigest(), "user_id": str(user["_id"]),
        "email": email, "user_type": "restaurant", "generation": user["password_reset_generation"],
        "whatsapp_binding_version": user["whatsapp_binding_version"], "used": False,
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
    })
    change = services.call("PATCH", f"/hub/tenants/{tid}", json={"whatsapp_phone": "11987654321"})
    assert change.status_code == 200, change.text
    updated = services.db.tenant_users.find_one({"_id": user["_id"]})
    assert updated["whatsapp_binding_version"] != user["whatsapp_binding_version"]
    assert updated["whatsapp_number"] == "+5511987654321"
    reset = services.call("POST", "/auth/reset-password", json={"token": token, "password": "not-a-real-password"})
    assert reset.status_code == 400
    assert services.db.tenant_users.find_one({"_id": user["_id"]}) is not None

    other = services.call("POST", "/hub/tenants", json={"name": f"Other {tag}",
        "owner_name": "Other", "email": f"other-{email}", "status": "active"})
    assert other.status_code == 200, other.text
    cross_tenant = services.call("PUT", f"/hub/tenants/{other.json()['id']}/whatsapp", json={
        "user_id": str(user["_id"]), "phone": "11912345678"})
    assert cross_tenant.status_code == 404


def test_concurrent_rotation_and_recovery_keep_old_links_invalid(services):
    tag = secrets.token_hex(6)
    email = f"race-{tag}@example.com"
    response = services.call("POST", "/hub/tenants/onboard", json={
        "name": f"Race {tag}", "owner_name": "Owner", "email": email,
        "status": "active", "whatsapp_phone": "11912345678", "create_hub_access": True,
    })
    assert response.status_code == 200, response.text
    tid = response.json()["id"]
    user = services.db.tenant_users.find_one({"tenant_id": tid, "email": email})
    previous = user["whatsapp_binding_version"]
    token = secrets.token_urlsafe(32)
    services.db.password_reset_tokens.insert_one({
        "token_hash": hashlib.sha256(token.encode()).hexdigest(), "user_id": str(user["_id"]),
        "email": email, "user_type": "restaurant", "generation": user["password_reset_generation"],
        "whatsapp_binding_version": previous, "used": False,
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
    })
    with ThreadPoolExecutor(max_workers=2) as pool:
        rotate = pool.submit(services.call, "PATCH", f"/hub/tenants/{tid}", json={"whatsapp_phone": "11987654321"})
        recover = pool.submit(services.call, "POST", "/auth/forgot-password", json={"email": email, "channel": "whatsapp"})
        assert rotate.result().status_code == 200
        assert recover.result().status_code == 200
    user = services.db.tenant_users.find_one({"_id": user["_id"]})
    assert user["whatsapp_binding_version"] != previous
    assert services.call("POST", "/auth/reset-password", json={"token": token, "password": "not-a-real-password"}).status_code == 400


def test_recovery_requests_are_generic_and_atomically_counted(services):
    email = f"missing-{secrets.token_hex(6)}@example.com"
    now = datetime.now(timezone.utc)
    with ThreadPoolExecutor(max_workers=10) as pool:
        calls = [pool.submit(services.call, "POST", "/auth/forgot-password",
                             json={"email": email, "channel": "whatsapp"}) for _ in range(10)]
        responses = [call.result() for call in calls]
    assert all(response.status_code == 200 for response in responses)
    assert len({response.text for response in responses}) == 1
    key = hashlib.sha256(f"account:{email}".encode()).hexdigest()
    assert services.db.password_reset_cooldowns.count_documents({"_id": key}) == 1


def test_parallel_recovery_does_not_continuously_invalidate_links(services):
    tag = secrets.token_hex(6)
    email = f"cooldown-{tag}@example.com"
    response = services.call("POST", "/hub/tenants/onboard", json={
        "name": f"Cooldown {tag}", "owner_name": "Owner", "email": email,
        "status": "active", "whatsapp_phone": "11912345678", "create_hub_access": True,
    })
    assert response.status_code == 200
    with ThreadPoolExecutor(max_workers=10) as pool:
        calls = [pool.submit(services.call, "POST", "/auth/forgot-password",
                             json={"email": email, "channel": "whatsapp"}) for _ in range(10)]
        assert all(call.result().status_code == 200 for call in calls)
    # One onboarding link and at most one recovery link were generated.
    assert services.db.password_reset_tokens.count_documents({"email": email}) <= 2


def test_transaction_rolls_back_phone_change_on_duplicate_slug(services):
    tag = secrets.token_hex(6)
    email = f"rollback-{tag}@example.com"
    first = services.call("POST", "/hub/tenants/onboard", json={
        "name": f"Rollback {tag}", "owner_name": "Owner", "email": email,
        "status": "active", "whatsapp_phone": "11912345678", "create_hub_access": True,
    })
    assert first.status_code == 200
    second_name = f"Already exists {tag}"
    second = services.call("POST", "/hub/tenants", json={
        "name": second_name, "owner_name": "Other", "email": f"other-{tag}@example.com", "status": "active",
    })
    assert second.status_code == 200
    tid = first.json()["id"]
    before = services.db.tenant_users.find_one({"tenant_id": tid, "email": email})
    result = services.call("PATCH", f"/hub/tenants/{tid}", json={
        "name": second_name, "whatsapp_phone": "11987654321",
    })
    assert result.status_code in (409, 503)
    after = services.db.tenant_users.find_one({"_id": before["_id"]})
    assert after["whatsapp_number"] == before["whatsapp_number"]
    assert after["whatsapp_binding_version"] == before["whatsapp_binding_version"]
    assert after["whatsapp_audit"] == before["whatsapp_audit"]
    tenant = services.db.tenants.find_one({"_id": ObjectId(tid)})
    assert tenant["whatsapp_phone"] == before["whatsapp_number"]


def test_untrusted_forwarded_for_cannot_choose_recovery_origin(services):
    email = f"origin-{secrets.token_hex(6)}@example.com"
    now = datetime.now(timezone.utc)
    headers = {"X-Forwarded-For": "198.51.100.87"}
    response = services.call("POST", "/auth/forgot-password", headers=headers,
                             json={"email": email, "channel": "email"})
    assert response.status_code == 200
    buckets = {int(now.timestamp()) // 900, int(datetime.now(timezone.utc).timestamp()) // 900}
    real_keys = [hashlib.sha256(f"origin:127.0.0.1:{bucket}".encode()).hexdigest() for bucket in buckets]
    fake_keys = [hashlib.sha256(f"origin:198.51.100.87:{bucket}".encode()).hexdigest() for bucket in buckets]
    assert services.db.password_reset_requests.count_documents({"_id": {"$in": real_keys}}) > 0
    assert services.db.password_reset_requests.count_documents({"_id": {"$in": fake_keys}}) == 0


def test_account_cooldown_is_sliding_and_permits_later_retry(services):
    tag = secrets.token_hex(6)
    email = f"window-{tag}@example.com"
    created = services.call("POST", "/hub/tenants/onboard", json={
        "name": f"Window {tag}", "owner_name": "Owner", "email": email,
        "status": "active", "whatsapp_phone": "11912345678", "create_hub_access": True,
    })
    assert created.status_code == 200
    key = hashlib.sha256(f"account:{email}".encode()).hexdigest()
    # The shared local origin quota may have been used by earlier tests.
    origin = hashlib.sha256(f"origin:127.0.0.1:{int(datetime.now(timezone.utc).timestamp()) // 900}".encode()).hexdigest()
    services.db.password_reset_requests.update_one({"_id": origin}, {"$set": {"count": 0}}, upsert=True)
    for _ in range(2):
        assert services.call("POST", "/auth/forgot-password", json={"email": email, "channel": "whatsapp"}).status_code == 200
    assert services.db.password_reset_tokens.count_documents({"email": email}) == 2
    services.db.password_reset_cooldowns.update_one({"_id": key}, {"$set": {"last_allowed": datetime.now(timezone.utc) - timedelta(minutes=16)}})
    assert services.call("POST", "/auth/forgot-password", json={"email": email, "channel": "whatsapp"}).status_code == 200
    assert services.db.password_reset_tokens.count_documents({"email": email}) == 3


def test_global_and_origin_limits_suppress_new_requests(services):
    bucket = int(datetime.now(timezone.utc).timestamp()) // 900
    keys = [(hashlib.sha256(f"global:all:{bucket}".encode()).hexdigest(), 500),
            (hashlib.sha256(f"origin:127.0.0.1:{bucket}".encode()).hexdigest(), 20)]
    for key, limit in keys:
        email = f"limited-{secrets.token_hex(6)}@example.com"
        account_key = hashlib.sha256(f"account:{email}".encode()).hexdigest()
        original = services.db.password_reset_requests.find_one({"_id": key}) or {}
        try:
            services.db.password_reset_requests.update_one({"_id": key}, {"$set": {"count": limit}}, upsert=True)
            result = services.call("POST", "/auth/forgot-password", json={"email": email, "channel": "email"})
            assert result.status_code == 200
            assert services.db.password_reset_cooldowns.count_documents({"_id": account_key}) == 0
        finally:
            services.db.password_reset_requests.update_one({"_id": key}, {"$set": {"count": original.get("count", 0)}})


def test_concurrent_phone_changes_keep_both_documents_consistent(services):
    tag = secrets.token_hex(6)
    email = f"rotate-{tag}@example.com"
    response = services.call("POST", "/hub/tenants/onboard", json={
        "name": f"Rotate {tag}", "owner_name": "Owner", "email": email,
        "status": "active", "whatsapp_phone": "11912345678", "create_hub_access": True,
    })
    assert response.status_code == 200
    tid = response.json()["id"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        operations = [pool.submit(services.call, "PATCH", f"/hub/tenants/{tid}", json={"whatsapp_phone": number})
                      for number in ("11987654321", "11976543210")]
        results = [operation.result() for operation in operations]
    assert all(result.status_code == 200 for result in results)
    owner = services.db.tenant_users.find_one({"tenant_id": tid, "email": email})
    tenant = services.db.tenants.find_one({"_id": ObjectId(tid)})
    assert tenant["whatsapp_phone"] == owner["whatsapp_number"]
    assert owner["whatsapp_number"] in {"+5511987654321", "+5511976543210"}


def test_actual_reset_revokes_existing_session_and_rejects_reuse(services):
    identity = services.restaurant()
    user = services.db.tenant_users.find_one({"_id": ObjectId(identity["uid"])})
    raw = secrets.token_urlsafe(32)
    services.db.password_reset_tokens.insert_one({
        "token_hash": hashlib.sha256(raw.encode()).hexdigest(), "user_id": identity["uid"],
        "email": user["email"], "user_type": "restaurant", "generation": user.get("password_reset_generation"),
        "used": False, "expires_at": datetime.now(timezone.utc) + timedelta(minutes=5),
    })
    password = secrets.token_urlsafe(16)
    reset = services.call("POST", "/auth/reset-password", json={"token": raw, "password": password})
    assert reset.status_code == 200
    assert services.call("GET", "/auth/me", headers=identity["headers"]).status_code == 401
    assert services.call("POST", "/auth/reset-password", json={"token": raw, "password": password}).status_code == 400
    assert services.login(user["email"], password)
