"""P0 coverage for the default-off internal Pedidos direct-login contract."""

import asyncio
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import importlib.util
import secrets
import socket
import sys
from types import SimpleNamespace
from pathlib import Path

from bson import ObjectId
from pymongo.errors import PyMongoError
import requests


BACKEND = Path(__file__).resolve().parents[1]


DIRECT_LOGIN_PATH = "/internal/modules/orders/direct-login/v1"
DIRECT_LOGIN_FIELDS = {
    "contract_version", "user_id", "restaurant_id", "name", "email",
    "module", "role", "access_versions",
}


@contextmanager
def _direct_login_enabled(services, *, trust_local_proxy=False):
    original_hub_env = services.env.copy()
    original_orders_env = services.orders_env.copy()
    services.env["ORDERS_DIRECT_LOGIN_ENABLED"] = "true"
    services.orders_env["ORDERS_DIRECT_LOGIN_ENABLED"] = "true"
    if trust_local_proxy:
        services.env["RECOVERY_TRUSTED_PROXY_CIDRS"] = "127.0.0.1/32"
    services.restart_hub()
    services.restart_orders()
    try:
        yield
    finally:
        services.env.clear()
        services.env.update(original_hub_env)
        services.orders_env.clear()
        services.orders_env.update(original_orders_env)
        services.restart_hub()
        services.restart_orders()


def _restaurant_user(services, identity):
    return services.db.tenant_users.find_one({"_id": ObjectId(identity["uid"])})


def _add_backup_admin(services, identity):
    response = services.call("POST", f"/hub/tenants/{identity['tid']}/users", json={
        "name": "Backup Admin",
        "email": f"backup-{secrets.token_hex(8)}@example.com",
        "role": "admin",
        "password": services.password,
    })
    response.raise_for_status()
    return response.json()


def _transfer_portal_owner(services, identity, replacement):
    services.call(
        "PUT", f"/hub/tenants/{identity['tid']}/portal-owner",
        json={"user_id": replacement["id"]},
    ).raise_for_status()


def _direct_login(services, email, password, *, module_key=None, extra=None, origin=None, hub_url=None):
    payload = {"email": email, "password": password}
    if extra:
        payload.update(extra)
    headers = {} if module_key is None else {"X-Module-Key": module_key}
    if origin:
        headers["X-Forwarded-For"] = origin
    return requests.post(
        (hub_url or services.hub) + "/api" + DIRECT_LOGIN_PATH,
        json=payload, headers=headers, timeout=10,
    )


def _orders_login(services, email, password):
    return requests.post(
        services.orders + "/api/auth/login",
        json={"email": email, "password": password},
        timeout=10,
    )


def _port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@contextmanager
def _second_hub_instance(services):
    name = "hub-direct-login-secondary"
    port = _port()
    services.start(
        name,
        [sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(port),
         "--no-proxy-headers"],
        services.hub_backend,
        services.env,
    )
    hub_url = f"http://127.0.0.1:{port}"
    try:
        services.wait(lambda: requests.get(hub_url + "/api/", timeout=1).raise_for_status(), name)
        yield hub_url
    finally:
        services.stop(name)


def _rate_key(services, scope, value):
    return hmac.new(
        services.env["JWT_SECRET"].encode("utf-8"),
        f"orders-direct-login:v1:{scope}:{value}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def test_direct_login_is_default_off(services):
    identity = services.restaurant()
    user = _restaurant_user(services, identity)
    response = _direct_login(services, user["email"], services.password, module_key=services.key)
    assert response.status_code == 404


def test_direct_login_returns_only_authoritative_orders_contract(services):
    identity = services.restaurant()
    user = _restaurant_user(services, identity)
    with _direct_login_enabled(services):
        response = _direct_login(services, user["email"], services.password, module_key=services.key)

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    contract = response.json()
    assert set(contract) == DIRECT_LOGIN_FIELDS
    assert contract["contract_version"] == 1
    assert contract["user_id"] == identity["uid"]
    assert contract["restaurant_id"] == identity["tid"]
    assert contract["name"] == user["name"]
    assert contract["email"] == user["email"]
    assert contract["module"] == "orders"
    assert contract["role"] == user["role"]
    assert set(contract["access_versions"]) == {"user", "tenant", "module"}
    assert all(type(value) is int and value >= 0 for value in contract["access_versions"].values())
    assert "password" not in response.text.lower()
    assert "token" not in response.text.lower()
    assert "set-cookie" not in response.headers


def test_direct_login_rejects_invalid_credentials_and_strict_body(services):
    identity = services.restaurant()
    user = _restaurant_user(services, identity)
    with _direct_login_enabled(services):
        wrong_password = _direct_login(services, user["email"], "wrong-password", module_key=services.key)
        unknown_user = _direct_login(
            services, f"missing-{secrets.token_hex(8)}@example.com", "wrong-password", module_key=services.key,
        )
        extra_field = _direct_login(
            services, user["email"], services.password, module_key=services.key,
            extra={"restaurant_id": identity["tid"]},
        )

    assert wrong_password.status_code == unknown_user.status_code == 401
    assert wrong_password.json() == unknown_user.json() == {"detail": "Credenciais inválidas"}
    assert extra_field.status_code == 422


def test_direct_login_requires_valid_module_key(services):
    identity = services.restaurant()
    user = _restaurant_user(services, identity)
    with _direct_login_enabled(services):
        missing = _direct_login(services, user["email"], services.password)
        invalid = _direct_login(services, user["email"], services.password, module_key="not-the-module-key")

    assert missing.status_code == invalid.status_code == 401
    assert missing.json() == invalid.json() == {"detail": "Chave de módulo inválida"}


def test_direct_login_derives_tenant_only_from_the_authenticated_user(services):
    first = services.restaurant()
    second = services.restaurant()
    first_user = _restaurant_user(services, first)
    second_user = _restaurant_user(services, second)
    with _direct_login_enabled(services):
        first_response = _direct_login(services, first_user["email"], services.password, module_key=services.key)
        second_response = _direct_login(services, second_user["email"], services.password, module_key=services.key)
        attempted_override = _direct_login(
            services, first_user["email"], services.password, module_key=services.key,
            extra={"restaurant_id": second["tid"]},
        )

    assert first_response.status_code == second_response.status_code == 200
    assert first_response.json()["restaurant_id"] == first["tid"]
    assert second_response.json()["restaurant_id"] == second["tid"]
    assert attempted_override.status_code == 422


def test_orders_direct_login_uses_real_hub_and_orders_backends(services):
    """Exercise the complete service boundary against the disposable MongoDB."""
    first = services.restaurant()
    second = services.restaurant()
    first_user = _restaurant_user(services, first)
    second_user = _restaurant_user(services, second)

    # ``Services.restaurant`` assigns an explicit portal owner before module
    # activation. That owner uses the passwordless Hub-managed provisioning
    # contract, so a later handoff never routes to Pedidos' local password
    # change page.
    preprovisioned = services.odb.users.find_one({
        "restaurant_id": first["tid"], "hub_user_id": first["uid"],
    })
    assert preprovisioned is not None
    assert preprovisioned["provisioned_by"] == "hub_direct_login"
    assert not preprovisioned.get("password_hash")
    assert not preprovisioned.get("must_change_password")

    with _direct_login_enabled(services):
        # Two browser requests race through the real Pedidos API to the real
        # HUB endpoint.  The unique mirror key must keep one local identity.
        with ThreadPoolExecutor(max_workers=2) as executor:
            concurrent_logins = list(executor.map(
                lambda _index: _orders_login(services, first_user["email"], services.password),
                range(2),
            ))
        assert [response.status_code for response in concurrent_logins] == [200, 200]
        first_login = concurrent_logins[0]
        second_login = _orders_login(services, second_user["email"], services.password)

        assert first_login.status_code == second_login.status_code == 200
        first_session = first_login.json()
        second_session = second_login.json()
        assert first_session["user"]["restaurant_id"] == first["tid"]
        assert second_session["user"]["restaurant_id"] == second["tid"]
        assert first_session["user"]["restaurant_id"] != second_session["user"]["restaurant_id"]
        assert services.order_me(first_session["token"]).status_code == 200
        assert services.order_me(second_session["token"]).status_code == 200

        mirror = services.odb.users.find_one({
            "restaurant_id": first["tid"], "hub_user_id": first["uid"],
        })
        assert mirror is not None
        assert mirror["account_origin"] == "hub"
        # Direct login preserves the pre-existing operational mirror and its
        # provenance; it never needs or receives a local HUB password.
        assert mirror["id"] == preprovisioned["id"]
        assert mirror["provisioned_by"] == "hub_direct_login"
        assert not mirror.get("password_hash")
        assert services.odb.users.count_documents({
            "restaurant_id": first["tid"], "hub_user_id": first["uid"],
        }) == 1

        # A second direct sign-in preserves the operational mirror identifier.
        repeated = _orders_login(services, first_user["email"], services.password)
        assert repeated.status_code == 200
        assert repeated.json()["user"]["id"] == first_session["user"]["id"]

        # The existing handoff continues to issue a Pedidos session while the
        # direct-login gate is enabled in this isolated environment.
        handoff = services.exchange(services.handoff(first))
        assert handoff.status_code == 200
        assert handoff.json()["user"]["must_change_password"] is False
        assert services.order_me(handoff.json()["token"]).status_code == 200


def test_orders_direct_login_denies_invalid_credentials_and_revoked_access(services):
    identity = services.restaurant()
    user = _restaurant_user(services, identity)
    inactive_user = services.restaurant()
    suspended_tenant = services.restaurant()
    disabled_module = services.restaurant()
    inactive_user_record = _restaurant_user(services, inactive_user)
    suspended_tenant_user = _restaurant_user(services, suspended_tenant)
    disabled_module_user = _restaurant_user(services, disabled_module)

    _transfer_portal_owner(services, inactive_user, _add_backup_admin(services, inactive_user))
    services.call(
        "PATCH", f"/hub/tenants/{inactive_user['tid']}/users/{inactive_user['uid']}",
        json={"status": "inactive"},
    ).raise_for_status()
    services.call(
        "PATCH", f"/hub/tenants/{suspended_tenant['tid']}", json={"status": "suspended"},
    ).raise_for_status()
    services.call(
        "POST", f"/hub/tenants/{disabled_module['tid']}/modules/orders/deactivate",
    ).raise_for_status()

    with _direct_login_enabled(services):
        assert _orders_login(services, user["email"], "wrong-password").status_code == 401
        assert _orders_login(services, inactive_user_record["email"], services.password).status_code == 401
        assert _orders_login(services, suspended_tenant_user["email"], services.password).status_code == 401
        assert _orders_login(services, disabled_module_user["email"], services.password).status_code == 401

        granted = _orders_login(services, user["email"], services.password)
        assert granted.status_code == 200

        services.call(
            "PUT", f"/hub/tenants/{identity['tid']}/modules/orders/users/{identity['uid']}/access",
            json={"active": False},
        ).raise_for_status()

        # A revoked grant prevents a new Pedidos session and invalidates an
        # already issued session through the existing fresh HUB revalidation.
        assert _orders_login(services, user["email"], services.password).status_code == 401
        assert services.order_me(granted.json()["token"]).status_code == 403


def test_direct_login_denies_inactive_user_tenant_disabled_module_and_grant(services):
    inactive_user = services.restaurant()
    inactive_tenant = services.restaurant()
    disabled_module = services.restaurant()
    revoked_grant = services.restaurant()
    users = [_restaurant_user(services, identity) for identity in (
        inactive_user, inactive_tenant, disabled_module, revoked_grant,
    )]

    _transfer_portal_owner(services, inactive_user, _add_backup_admin(services, inactive_user))
    services.call(
        "PATCH", f"/hub/tenants/{inactive_user['tid']}/users/{inactive_user['uid']}",
        json={"status": "inactive"},
    ).raise_for_status()
    services.call("PATCH", f"/hub/tenants/{inactive_tenant['tid']}", json={"status": "suspended"}).raise_for_status()
    services.call("POST", f"/hub/tenants/{disabled_module['tid']}/modules/orders/deactivate").raise_for_status()
    services.call(
        "PUT", f"/hub/tenants/{revoked_grant['tid']}/modules/orders/users/{revoked_grant['uid']}/access",
        json={"active": False},
    ).raise_for_status()

    with _direct_login_enabled(services):
        responses = [
            _direct_login(services, user["email"], services.password, module_key=services.key)
            for user in users
        ]

    assert [response.status_code for response in responses] == [401, 401, 401, 401]
    assert all(response.json() == {"detail": "Credenciais inválidas"} for response in responses)


def test_direct_login_rate_limits_repeated_failures_by_account(services):
    identity = services.restaurant()
    user = _restaurant_user(services, identity)
    origin = "198.51.100.200"
    with _direct_login_enabled(services, trust_local_proxy=True):
        failures = [
            _direct_login(services, user["email"], "wrong-password", module_key=services.key, origin=origin)
            for _ in range(5)
        ]
        limited = _direct_login(services, user["email"], "wrong-password", module_key=services.key, origin=origin)

    assert [response.status_code for response in failures] == [401] * 5
    assert limited.status_code == 429
    counter = services.db.orders_direct_login_rate_limits.find_one({
        "_id": _rate_key(services, "account", user["email"]),
    })
    assert set(counter) == {"_id", "window_started_at", "count", "expires_at"}
    assert user["email"] not in str(counter)
    assert "password" not in str(counter).lower()


def test_direct_login_account_limit_resists_distributed_origins(services):
    identity = services.restaurant()
    user = _restaurant_user(services, identity)
    with _direct_login_enabled(services, trust_local_proxy=True):
        failures = [
            _direct_login(
                services, user["email"], "wrong-password", module_key=services.key,
                origin=f"198.51.100.{index}",
            )
            for index in range(1, 6)
        ]
        limited = _direct_login(
            services, user["email"], "wrong-password", module_key=services.key,
            origin="198.51.100.99",
        )

    assert [response.status_code for response in failures] == [401] * 5
    assert limited.status_code == 429


def test_direct_login_origin_limit_is_independent_of_account(services):
    origin = "198.51.100.201"
    with _direct_login_enabled(services, trust_local_proxy=True):
        failures = [
            _direct_login(
                services, f"origin-limit-{index}-{secrets.token_hex(4)}@example.com", "wrong-password",
                module_key=services.key, origin=origin,
            )
            for index in range(50)
        ]
        limited = _direct_login(
            services, f"origin-limit-{secrets.token_hex(8)}@example.com", "wrong-password",
            module_key=services.key, origin=origin,
        )

    assert [response.status_code for response in failures] == [401] * 50
    assert limited.status_code == 429


def test_direct_login_counter_is_atomic_across_concurrent_hub_instances(services):
    identity = services.restaurant()
    user = _restaurant_user(services, identity)
    with _direct_login_enabled(services, trust_local_proxy=True), _second_hub_instance(services) as second_hub:
        def attempt(index):
            return _direct_login(
                services, user["email"], "wrong-password", module_key=services.key,
                origin=f"203.0.113.{index + 1}", hub_url=services.hub if index % 2 else second_hub,
            ).status_code

        with ThreadPoolExecutor(max_workers=16) as executor:
            statuses = list(executor.map(attempt, range(16)))

    assert statuses.count(401) == 5
    assert statuses.count(429) == 11


def test_direct_login_expired_window_resets_without_waiting_for_ttl(services):
    identity = services.restaurant()
    user = _restaurant_user(services, identity)
    origin = "198.51.100.202"
    with _direct_login_enabled(services, trust_local_proxy=True):
        for _ in range(5):
            assert _direct_login(
                services, user["email"], "wrong-password", module_key=services.key, origin=origin,
            ).status_code == 401
        assert _direct_login(
            services, user["email"], "wrong-password", module_key=services.key, origin=origin,
        ).status_code == 429
        expired_at = datetime.now(timezone.utc) - timedelta(minutes=16)
        future_expiry = datetime.now(timezone.utc) + timedelta(minutes=1)
        for scope, value in (("account", user["email"]), ("origin", origin)):
            services.db.orders_direct_login_rate_limits.update_one(
                {"_id": _rate_key(services, scope, value)},
                {"$set": {"window_started_at": expired_at, "expires_at": future_expiry}},
            )
        renewed = _direct_login(
            services, user["email"], "wrong-password", module_key=services.key, origin=origin,
        )

    assert renewed.status_code == 401
    account = services.db.orders_direct_login_rate_limits.find_one({
        "_id": _rate_key(services, "account", user["email"]),
    })
    assert account["count"] == 1


def test_direct_login_rate_limiter_fails_closed_on_mongodb_error(monkeypatch):
    for key, value in {
        "MONGO_URL": "mongodb://127.0.0.1:27017", "DB_NAME": "direct_login_unit",
        "JWT_SECRET": "j" * 40, "HANDOFF_JWT_SECRET": "h" * 40,
        "MODULE_API_KEY": "m" * 40, "ADMIN_EMAIL": "admin@example.test",
        "ADMIN_PASSWORD": "p" * 20, "FRONTEND_URL": "https://hub.example.test",
    }.items():
        monkeypatch.setenv(key, value)
    sys.path.insert(0, str(BACKEND))
    try:
        spec = importlib.util.spec_from_file_location("direct_login_server_test", BACKEND / "server.py")
        module = importlib.util.module_from_spec(spec)
        assert spec.loader
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(BACKEND))

    class UnavailableCollection:
        async def find_one_and_update(self, *args, **kwargs):
            raise PyMongoError("synthetic MongoDB outage")

    module.db = SimpleNamespace(orders_direct_login_rate_limits=UnavailableCollection())
    assert asyncio.run(module._allow_orders_direct_login_attempt("user@example.test", "127.0.0.1")) is False
