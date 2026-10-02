"""P0 coverage for server-side sessions independently scoped to browser tabs."""

import hashlib
import uuid
from datetime import datetime, timezone

import requests
from bson import ObjectId


def _binding(headers):
    return headers["Cookie"].split("=", 1)[1]


def test_browser_binding_is_secure_http_only_session_cookie(services):
    login = requests.post(
        services.hub + "/api/auth/login",
        json={"email": services.admin_email, "password": services.password},
        headers={"X-DACOT-Tab-Session": str(uuid.uuid4())}, timeout=10,
    )
    assert login.status_code == 200, login.text
    cookies = [item for item in login.raw.headers.getlist("Set-Cookie") if item.startswith("__Host-dacot_browser=")]
    assert len(cookies) == 1
    cookie = cookies[0]
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=none" in cookie, cookie
    assert "Path=/" in cookie and "Domain=" not in cookie, cookie
    assert "Max-Age" not in cookie and "expires=" not in cookie.lower(), cookie


def test_tab_sessions_are_independent_and_logout_is_scoped(services):
    a = services.login(services.admin_email, services.password)
    b = services.login(
        services.admin_email, services.password,
        browser_binding=_binding(a), tab_session_id=str(uuid.uuid4()),
    )
    assert requests.get(services.hub + "/api/auth/me", headers=a, timeout=10).status_code == 200
    assert requests.get(services.hub + "/api/auth/me", headers=b, timeout=10).status_code == 200

    assert requests.post(services.hub + "/api/auth/logout", headers=a, timeout=10).status_code == 200
    assert requests.get(services.hub + "/api/auth/me", headers=a, timeout=10).status_code == 401
    assert requests.post(services.hub + "/api/auth/refresh", headers=a, timeout=10).status_code == 401
    assert requests.get(services.hub + "/api/auth/me", headers=b, timeout=10).status_code == 200
    assert requests.post(services.hub + "/api/auth/refresh", headers=b, timeout=10).status_code == 200

    assert requests.post(services.hub + "/api/auth/logout", headers=b, timeout=10).status_code == 200
    assert requests.get(services.hub + "/api/auth/me", headers=b, timeout=10).status_code == 401


def test_auth_fails_closed_for_missing_or_mixed_session_identifiers(services):
    identity = services.login(services.admin_email, services.password)
    no_tab = {"Cookie": identity["Cookie"]}
    no_binding = {"X-DACOT-Tab-Session": identity["X-DACOT-Tab-Session"]}
    mixed = {"Cookie": identity["Cookie"], "X-DACOT-Tab-Session": str(uuid.uuid4())}
    for headers in (no_tab, no_binding, mixed):
        assert requests.get(services.hub + "/api/auth/me", headers=headers, timeout=10).status_code == 401
        assert requests.post(services.hub + "/api/auth/refresh", headers=headers, timeout=10).status_code == 401

    # An obsolete JWT-named cookie, with no valid server-side session pair,
    # never authenticates a browser request.
    assert requests.get(
        services.hub + "/api/auth/me", headers={"Cookie": "access_token=legacy"}, timeout=10
    ).status_code == 401


def test_expired_and_globally_revoked_sessions_fail_closed(services):
    identity = services.login(services.admin_email, services.password)
    binding = _binding(identity)
    services.db.auth_sessions.update_one(
        {"browser_binding_hash": hashlib.sha256(binding.encode()).hexdigest(),
         "tab_session_id_hash": hashlib.sha256(identity["X-DACOT-Tab-Session"].encode()).hexdigest()},
        {"$set": {"access_expires_at": datetime.now(timezone.utc),
                  "refresh_expires_at": datetime.now(timezone.utc)}},
    )
    assert requests.get(services.hub + "/api/auth/me", headers=identity, timeout=10).status_code == 401
    assert requests.post(services.hub + "/api/auth/refresh", headers=identity, timeout=10).status_code == 401

    identity = services.login(services.admin_email, services.password)
    admin = services.db.hub_users.find_one({"email": services.admin_email})
    original_version = admin.get("token_version", 0)
    services.db.hub_users.update_one({"_id": admin["_id"]}, {"$inc": {"token_version": 1}})
    assert requests.get(services.hub + "/api/auth/me", headers=identity, timeout=10).status_code == 401
    services.db.hub_users.update_one({"_id": admin["_id"]}, {"$set": {"token_version": original_version}})


def test_handoff_requires_a_live_tab_session(services):
    restaurant = services.restaurant()
    assert requests.post(
        services.hub + "/api/portal/modules/orders/launch-token", headers=restaurant["headers"], timeout=10
    ).status_code == 200
    assert requests.post(
        services.hub + "/api/auth/logout", headers=restaurant["headers"], timeout=10
    ).status_code == 200
    assert requests.post(
        services.hub + "/api/portal/modules/orders/launch-token", headers=restaurant["headers"], timeout=10
    ).status_code == 401


def test_restaurant_user_and_tenant_state_have_separate_semantics(services):
    inactive_user = services.restaurant()
    services.db.tenant_users.update_one(
        {"_id": ObjectId(inactive_user["uid"])}, {"$set": {"status": "inactive"}}
    )
    assert requests.get(
        services.hub + "/api/auth/me", headers=inactive_user["headers"], timeout=10
    ).status_code == 401

    suspended_tenant = services.restaurant()
    services.db.tenants.update_one(
        {"_id": ObjectId(suspended_tenant["tid"])}, {"$set": {"status": "suspended"}}
    )
    # A tenant state transition is an operational authorization decision, not
    # a browser-session revocation. The identity remains valid, while the
    # handoff dependency rejects a non-operational tenant with 403.
    assert requests.get(
        services.hub + "/api/auth/me", headers=suspended_tenant["headers"], timeout=10
    ).status_code == 200
    assert requests.post(
        services.hub + "/api/auth/refresh", headers=suspended_tenant["headers"], timeout=10
    ).status_code == 200
    assert requests.post(
        services.hub + "/api/portal/modules/orders/launch-token",
        headers=suspended_tenant["headers"], timeout=10,
    ).status_code == 403
