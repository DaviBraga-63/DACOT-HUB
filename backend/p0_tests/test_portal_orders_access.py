"""P0 coverage for owner-controlled, fail-closed Pedidos access."""

import socket
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from bson import ObjectId

from backend.p0_tests.test_orders_direct_login import _direct_login_enabled, _orders_login


def _grant(services, tid, uid):
    return services.db.module_user_grants.find_one(
        {"tenant_id": tid, "user_id": uid, "module_key": "orders"}
    )


def _create_employee(services, owner, email, *, role="waiter", custom_role_id=None):
    payload = {
        "name": "Funcionário de teste", "email": email, "role": role,
        "password": services.password,
    }
    if custom_role_id is not None:
        payload["custom_role_id"] = custom_role_id
    response = services.call("POST", "/portal/users", headers=owner["headers"], json=payload)
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _access_path(uid):
    return f"/portal/users/{uid}/orders/access"


def test_owner_can_authorize_pre_activation_employee_idempotently(services):
    owner = services.restaurant()
    services.call("POST", f"/hub/tenants/{owner['tid']}/modules/orders/deactivate").raise_for_status()
    uid = _create_employee(services, owner, "before-activation@example.com")
    assert _grant(services, owner["tid"], uid) is None
    assert services.odb.users.count_documents({"restaurant_id": owner["tid"], "hub_user_id": uid}) == 0

    services.call("POST", f"/hub/tenants/{owner['tid']}/modules/orders/activate").raise_for_status()
    first = services.call("PUT", _access_path(uid), headers=owner["headers"], json={"active": True})
    second = services.call("PUT", _access_path(uid), headers=owner["headers"], json={"active": True})

    assert first.status_code == second.status_code == 200
    assert _grant(services, owner["tid"], uid)["active"] is True
    assert services.odb.users.count_documents({"restaurant_id": owner["tid"], "hub_user_id": uid}) == 1


def test_new_employee_is_authorized_only_after_provision_and_custom_role_validation(services):
    owner = services.restaurant()
    role_id = "portal-access-role"
    services.odb.custom_roles.insert_one({
        "id": role_id, "restaurant_id": owner["tid"], "name": "Garçom líder",
        "name_key": "garçom líder", "permissions": ["orders.view"],
    })
    uid = _create_employee(services, owner, "new-custom-role@example.com", custom_role_id=role_id)

    grant = _grant(services, owner["tid"], uid)
    mirror = services.odb.users.find_one({"restaurant_id": owner["tid"], "hub_user_id": uid})
    assert grant["active"] is True and grant["configuration_state"] == "granted"
    assert mirror and mirror["custom_role_id"] == role_id


def test_pending_custom_role_configuration_is_retried_without_losing_the_association(services):
    owner = services.restaurant()
    response = services.call(
        "POST", "/portal/users", headers=owner["headers"],
        json={"name": "Garçom pendente", "email": "pending-custom@example.com", "role": "waiter",
              "password": services.password, "custom_role_id": "role-created-later"},
    )
    assert response.status_code == 503
    record = services.db.tenant_users.find_one({"email": "pending-custom@example.com"})
    uid = str(record["_id"])
    pending = _grant(services, owner["tid"], uid)
    assert pending["active"] is False and pending["configuration_state"] == "pending"
    assert pending["pending_custom_role_id"] == "role-created-later"

    services.odb.custom_roles.insert_one({
        "id": "role-created-later", "restaurant_id": owner["tid"], "name": "Garçom líder",
        "name_key": "garçom líder", "permissions": ["orders.view"],
    })
    retry = services.call("PUT", _access_path(uid), headers=owner["headers"], json={"active": True})
    assert retry.status_code == 200, retry.text
    mirror = services.odb.users.find_one({"restaurant_id": owner["tid"], "hub_user_id": uid})
    assert mirror["custom_role_id"] == "role-created-later"
    assert "pending_custom_role_id" not in _grant(services, owner["tid"], uid)


def test_owner_access_control_is_tenant_scoped_and_requires_active_employee_and_module(services):
    owner, other = services.restaurant(), services.restaurant()
    uid = _create_employee(services, owner, "tenant-scoped@example.com")
    assert services.call("PUT", _access_path(uid), headers=other["headers"], json={"active": False}).status_code == 404

    services.call("PATCH", f"/portal/users/{uid}", headers=owner["headers"], json={"status": "inactive"}).raise_for_status()
    assert services.call("PUT", _access_path(uid), headers=owner["headers"], json={"active": True}).status_code == 409

    services.call("PATCH", f"/portal/users/{uid}", headers=owner["headers"], json={"status": "active"}).raise_for_status()
    services.call("POST", f"/hub/tenants/{owner['tid']}/modules/orders/deactivate").raise_for_status()
    assert services.call("PUT", _access_path(uid), headers=owner["headers"], json={"active": True}).status_code == 400


def test_revoke_invalidates_existing_orders_session_and_module_deactivation_denies_it(services):
    owner = services.restaurant()
    email = "session-revocation@example.com"
    uid = _create_employee(services, owner, email)
    with _direct_login_enabled(services):
        login = _orders_login(services, email, services.password)
        assert login.status_code == 200, login.text
        assert services.call("PUT", _access_path(uid), headers=owner["headers"], json={"active": False}).status_code == 200
        assert services.order_me(login.json()["token"]).status_code == 403

        assert services.call("PUT", _access_path(uid), headers=owner["headers"], json={"active": True}).status_code == 200
        refreshed = _orders_login(services, email, services.password)
        assert refreshed.status_code == 200, refreshed.text
        services.call("POST", f"/hub/tenants/{owner['tid']}/modules/orders/deactivate").raise_for_status()
        assert services.order_me(refreshed.json()["token"]).status_code == 403


def test_unavailable_orders_keeps_pending_access_and_retry_reuses_mirror(services):
    owner = services.restaurant()
    services.call("POST", f"/hub/tenants/{owner['tid']}/modules/orders/deactivate").raise_for_status()
    uid = _create_employee(services, owner, "pending-retry@example.com")
    services.call("POST", f"/hub/tenants/{owner['tid']}/modules/orders/activate").raise_for_status()

    services.stop("orders")
    try:
        failed = services.call("PUT", _access_path(uid), headers=owner["headers"], json={"active": True})
        assert failed.status_code == 503
        grant = _grant(services, owner["tid"], uid)
        assert grant["active"] is False and grant["configuration_state"] == "pending"
    finally:
        services.restart_orders()

    assert services.call("PUT", _access_path(uid), headers=owner["headers"], json={"active": True}).status_code == 200
    assert services.odb.users.count_documents({"restaurant_id": owner["tid"], "hub_user_id": uid}) == 1


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@contextmanager
def _slow_orders_service():
    started, release = threading.Event(), threading.Event()

    class SlowOrders(BaseHTTPRequestHandler):
        def log_message(self, _format, *_args):
            pass

        def do_POST(self):
            started.set()
            assert release.wait(10)
            body = b'{"ok":true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            body = b'{"custom_role":null}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", _free_port()), SlowOrders)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", started, release
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_later_revoke_wins_over_a_concurrent_authorization(services):
    owner = services.restaurant()
    services.call("POST", f"/hub/tenants/{owner['tid']}/modules/orders/deactivate").raise_for_status()
    uid = _create_employee(services, owner, "concurrent-access@example.com")
    services.call("POST", f"/hub/tenants/{owner['tid']}/modules/orders/activate").raise_for_status()

    original_env = services.env.copy()
    with _slow_orders_service() as (orders_url, started, release):
        services.env["ORDERS_BACKEND_URL"] = orders_url
        services.restart_hub()
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                authorize = pool.submit(services.call, "PUT", _access_path(uid), headers=owner["headers"], json={"active": True})
                assert started.wait(5)
                # A second authorization must not race a custom-role or
                # provisioning write in Pedidos while the first is in flight.
                concurrent_authorize = services.call(
                    "PUT", _access_path(uid), headers=owner["headers"], json={"active": True}
                )
                revoked = services.call("PUT", _access_path(uid), headers=owner["headers"], json={"active": False})
                release.set()
                authorization = authorize.result(timeout=10)
            assert revoked.status_code == 200
            assert concurrent_authorize.status_code == 409
            assert authorization.status_code == 409
            grant = _grant(services, owner["tid"], uid)
            assert grant["active"] is False and grant["configuration_state"] == "blocked"
        finally:
            services.env.clear()
            services.env.update(original_env)
            services.restart_hub()
