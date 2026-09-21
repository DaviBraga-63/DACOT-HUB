import hashlib
import importlib.util
import secrets
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import bcrypt
from bson import ObjectId
import jwt
import pytest
import requests


BACKEND = Path(__file__).resolve().parents[1]


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("status", ["suspended", "inactive"])
def test_effective_status_and_suspended_handoff(services, status):
    s, identity = services, services.restaurant()
    token = s.handoff(identity)
    s.call("PATCH", f"/hub/tenants/{identity['tid']}", json={"status": status}).raise_for_status()
    result = s.call("GET", f"/public/tenants/{identity['tid']}/modules/orders/status", headers={"X-Module-Key": s.key})
    assert result.status_code == 200 and result.json()["active"] is False
    assert s.exchange(token).status_code == 403
    assert s.call("POST", "/portal/modules/orders/launch-token", headers=identity["headers"]).status_code == 403


def test_deactivated_module_rejects_pending_and_new_handoff(services):
    s, identity = services, services.restaurant()
    token = s.handoff(identity)
    s.call("POST", f"/hub/tenants/{identity['tid']}/modules/orders/deactivate").raise_for_status()
    assert s.exchange(token).status_code == 403
    assert s.call("POST", "/portal/modules/orders/launch-token", headers=identity["headers"]).status_code == 400


def test_disabled_user_cannot_handoff(services):
    s, identity = services, services.restaurant()
    token = s.handoff(identity)
    s.call("PATCH", f"/hub/tenants/{identity['tid']}/users/{identity['uid']}", json={"status": "inactive"}).raise_for_status()
    assert s.call("POST", "/portal/modules/orders/launch-token", headers=identity["headers"]).status_code == 401
    assert s.exchange(token).status_code == 403


@pytest.mark.parametrize("url", [
    "https://evil.example.test/a", "http://orders.example.test/a", "https://orders.example.test.evil.test/a",
    "https://orders.example.test@evil.test/a", "javascript:alert(1)", "//orders.example.test/a",
    "https://orders.example.test/a?redirect=https://evil.test", "https://orders.example.test/a#x",
    "https://orders.example.test\\@evil.test", "https://orders.example.test:8443/a",
])
def test_launch_url_validation(services, url):
    s = services
    # A real configured tenant; validation must happen server-side on write.
    tenant = s.db.tenants.find_one({})
    result = s.call("PATCH", f"/hub/tenants/{tenant['_id']}/modules/orders", json={"launch_url": url})
    assert result.status_code == 400


def test_existing_poisoned_destination_cannot_issue_token(services):
    s, identity = services, services.restaurant()
    s.db.tenant_modules.update_one({"tenant_id": identity["tid"], "module_key": "orders"}, {"$set": {"launch_url": "https://evil.test"}})
    assert s.call("POST", "/portal/modules/orders/launch-token", headers=identity["headers"]).status_code == 400


def test_local_requires_explicit_development_and_allowlist(monkeypatch):
    policy = load("policy", BACKEND / "handoff_policy.py")
    monkeypatch.setenv("HANDOFF_ALLOWED_ORIGINS_JSON", '{"orders":["http://127.0.0.1:3000"]}')
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(Exception) as error:
        policy.validate_launch_url("http://127.0.0.1:3000/r", "orders")
    assert error.value.status_code == 400
    monkeypatch.setenv("APP_ENV", "development")
    assert policy.validate_launch_url("http://127.0.0.1:3000/r", "orders").startswith("http:")
    monkeypatch.delenv("HANDOFF_ALLOWED_ORIGINS_JSON")
    with pytest.raises(Exception):
        policy.validate_launch_url("http://127.0.0.1:3000/r", "orders")


def test_legitimate_handoff_replay_expiration_and_staff(services):
    s, identity = services, services.restaurant()
    token = s.handoff(identity)
    result = s.exchange(token)
    assert result.status_code == 200, result.text
    assert result.json()["user"]["restaurant_id"] == identity["tid"]
    assert s.order_me(result.json()["token"]).status_code == 200
    assert s.exchange(token).status_code == 401
    claims = jwt.decode(token, s.secret, algorithms=["HS256"], audience="dacot-orders")
    claims.update(jti=secrets.token_hex(10), iat=int(time.time())-120, nbf=int(time.time())-120, exp=int(time.time())-60)
    assert s.exchange(jwt.encode(claims, s.secret, algorithm="HS256")).status_code == 401
    claims.update(jti=secrets.token_hex(10), iat=int(time.time()), nbf=int(time.time())-5, exp=int(time.time())+60, sub="hub_user:"+identity["uid"])
    assert s.exchange(jwt.encode(claims, s.secret, algorithm="HS256")).status_code == 401
    assert s.call("POST", f"/hub/tenants/{identity['tid']}/modules/orders/launch-token").status_code == 403


def test_two_restaurants_and_forged_subject_isolation(services):
    s, a, b = services, services.restaurant(), services.restaurant()
    token = s.handoff(a)
    claims = jwt.decode(token, s.secret, algorithms=["HS256"], audience="dacot-orders")
    claims.update(restaurant_id=b["tid"], jti=secrets.token_hex(10))
    assert s.exchange(jwt.encode(claims, s.secret, algorithm="HS256")).status_code == 403
    for identity in (a, b):
        result = s.exchange(s.handoff(identity))
        assert result.status_code == 200
        assert result.json()["user"]["restaurant_id"] == identity["tid"]
    context = s.call("GET", "/portal/context", headers=a["headers"])
    assert context.json()["tenant"]["id"] == a["tid"]
    assert s.call("GET", f"/hub/tenants/{b['tid']}", headers=a["headers"]).status_code == 403
    # Valid local sessions cannot read an order from the other restaurant.
    order_id = secrets.token_hex(12)
    s.odb.orders.insert_one({"id": order_id, "restaurant_id": b["tid"]})
    access = s.exchange(s.handoff(a)).json()["token"]
    r = requests.get(s.orders + f"/api/orders/{order_id}", headers={"Authorization": "Bearer " + access}, timeout=10)
    assert r.status_code == 404


def reset_password(s, uid, email, ut, password):
    raw = secrets.token_urlsafe(30)
    s.db.password_reset_tokens.insert_one({"token_hash": hashlib.sha256(raw.encode()).hexdigest(),
        "user_id": uid, "email": email, "user_type": ut, "used": False,
        "expires_at": datetime.now(timezone.utc)+timedelta(hours=1)})
    s.call("POST", "/auth/reset-password", json={"token": raw, "password": password}).raise_for_status()


def test_password_reset_survives_restart_and_missing_password_not_created(services):
    s = services
    admin = s.db.hub_users.find_one({"email": s.admin_email})
    new_password = secrets.token_urlsafe(20)
    old_headers = s.staff.copy()
    reset_password(s, str(admin["_id"]), s.admin_email, "staff", new_password)
    before = s.db.hub_users.find_one({"_id": admin["_id"]})
    missing = s.db.tenant_users.insert_one({"email": "no-password@example.com", "status": "active", "tenant_id": str(ObjectId())}).inserted_id
    s.restart_hub()
    after = s.db.hub_users.find_one({"_id": admin["_id"]})
    assert after["password_hash"] == before["password_hash"]
    assert after["token_version"] == before["token_version"]
    assert s.call("GET", "/auth/me", headers=old_headers).status_code == 401
    assert not s.db.tenant_users.find_one({"_id": missing}).get("password_hash")
    s.staff = s.login(s.admin_email, new_password)
    s.password = new_password


def test_legacy_audit_dry_run_quarantine_idempotence_and_recovery(services):
    s, identity = services, services.restaurant()
    migration = load("audit_legacy", BACKEND / "audit_legacy_passwords.py")
    candidate = secrets.token_urlsafe(20)  # synthetic historical password, never real
    uid = ObjectId(identity["uid"])
    hashed = bcrypt.hashpw(candidate.encode(), bcrypt.gensalt()).decode()
    s.db.tenant_users.update_one({"_id": uid}, {"$set": {"password_hash": hashed}})
    before = s.db.tenant_users.find_one({"_id": uid})
    assert any(x["id"] == str(uid) for x in migration.inspect_accounts(s.db, candidate))
    assert s.db.tenant_users.find_one({"_id": uid}) == before
    migration.inspect_accounts(s.db, candidate, True)
    after = s.db.tenant_users.find_one({"_id": uid})
    assert after["password_hash"] == hashed and after["password_reset_required"]
    assert after["token_version"] == before["token_version"] + 1
    migration.inspect_accounts(s.db, candidate, True)
    assert s.db.tenant_users.find_one({"_id": uid})["token_version"] == after["token_version"]
    assert s.call("POST", "/portal/modules/orders/launch-token", headers=identity["headers"]).status_code == 401
    reset_password(s, str(uid), before["email"], "restaurant", s.password)
    assert not s.db.tenant_users.find_one({"_id": uid})["password_reset_required"]
    assert s.login(before["email"], s.password)


def test_revocation_bound_reactivation_and_hub_outage(services):
    s = services
    identities = [s.restaurant() for _ in range(5)]
    sessions = [s.exchange(s.handoff(i)).json()["token"] for i in identities]
    for token in sessions:
        assert s.order_me(token).status_code == 200
    a, b, c, d, healthy = identities
    s.call("PATCH", f"/hub/tenants/{a['tid']}", json={"status": "suspended"}).raise_for_status()
    s.call("POST", f"/hub/tenants/{b['tid']}/modules/orders/deactivate").raise_for_status()
    s.call("PATCH", f"/hub/tenants/{c['tid']}/users/{c['uid']}", json={"status": "inactive"}).raise_for_status()
    s.call("PATCH", f"/hub/tenants/{d['tid']}/users/{d['uid']}", json={"role": "waiter"}).raise_for_status()
    s.stop("hub")
    assert s.order_me(sessions[-1]).status_code == 200  # unexpired lease remains usable
    time.sleep(61)  # real clock: validate configured production revocation bound
    assert s.order_me(sessions[-1]).status_code == 503  # no stale-while-error authorization
    s.restart_hub()
    for token in sessions[:-1]:
        assert s.order_me(token).status_code == 403
    assert s.order_me(sessions[-1]).status_code == 200
    s.call("PATCH", f"/hub/tenants/{a['tid']}", json={"status": "active"}).raise_for_status()
    s.call("POST", f"/hub/tenants/{b['tid']}/modules/orders/activate").raise_for_status()
    s.call("PATCH", f"/hub/tenants/{c['tid']}/users/{c['uid']}", json={"status": "active"}).raise_for_status()
    for token in sessions[:3]:
        assert s.order_me(token).status_code == 403  # old versions never resurrect
    for identity in (a, b):
        assert s.exchange(s.handoff(identity)).status_code == 200
