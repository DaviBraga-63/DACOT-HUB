import hashlib
from datetime import datetime, timedelta, timezone
import requests


def _new_tenant_and_user(services, tag):
    tenant = services.call("POST", "/hub/tenants", json={
        "name": f"Restaurant {tag}", "owner_name": "Owner",
        "email": f"owner-{tag}@example.com", "status": "active",
    })
    tenant.raise_for_status()
    tid = tenant.json()["id"]
    user = services.call("POST", f"/hub/tenants/{tid}/users", json={
        "name": f"Admin {tag}", "email": f"admin-{tag}@example.com",
        "role": "admin", "password": services.password,
    })
    user.raise_for_status()
    return tid, user.json()["id"], f"admin-{tag}@example.com"


def _issue_invite(services, tid, uid, email, tag="Invite"):
    response = requests.post(
        services.orders + "/api/internal/hub/provision",
        headers={"X-Module-Key": services.key},
        json={"tenant_id": tid, "tenant_name": f"Restaurant {tag}", "hub_user_id": uid,
              "name": f"Admin {tag}", "email": email, "role": "admin"}, timeout=10,
    )
    response.raise_for_status()
    return response.json()["invite_token"]


def test_activation_provisions_idempotently_and_direct_login_is_hub_authorized(services):
    tid, uid, email = _new_tenant_and_user(services, "provision")
    first = services.call("POST", f"/hub/tenants/{tid}/modules/orders/activate")
    assert first.status_code == 200, first.text
    second = services.call("POST", f"/hub/tenants/{tid}/modules/orders/activate")
    assert second.status_code == 200, second.text

    restaurant = services.odb.restaurants.find_one({"id": tid})
    assert restaurant["hub_tenant_id"] == tid
    assert services.odb.restaurants.count_documents({"id": tid}) == 1
    provisioned = services.odb.users.find_one({"hub_user_id": uid})
    assert provisioned["restaurant_id"] == tid
    assert provisioned["email"] == email
    assert provisioned["provisioned_by"] == "hub"
    assert provisioned["password_hash"] == ""
    assert services.odb.users.count_documents({"hub_user_id": uid}) == 1
    state = services.db.tenant_modules.find_one({"tenant_id": tid, "module_key": "orders"})
    assert state["provisioning_status"] == "succeeded"

    invitation = _issue_invite(services, tid, uid, email)
    first_access = requests.post(services.orders + "/api/auth/first-access", json={
        "token": invitation, "password": services.password,
    }, timeout=10)
    assert first_access.status_code == 200, first_access.text
    login = requests.post(services.orders + "/api/auth/login", json={"email": email, "password": services.password}, timeout=10)
    assert login.status_code == 200, login.text
    token = login.json()["token"]
    assert services.order_me(token).status_code == 200

    services.db.module_user_grants.update_one(
        {"tenant_id": tid, "user_id": uid, "module_key": "orders"}, {"$set": {"active": False}}
    )
    assert requests.post(services.orders + "/api/auth/login", json={"email": email, "password": services.password}, timeout=10).status_code == 403


def test_first_access_expiration_replay_replacement_and_tenant_binding(services):
    tid, uid, email = _new_tenant_and_user(services, "tokens")
    assert services.call("POST", f"/hub/tenants/{tid}/modules/orders/activate").status_code == 200
    old = _issue_invite(services, tid, uid, email, "Old")
    current = _issue_invite(services, tid, uid, email, "Current")
    endpoint = services.orders + "/api/auth/first-access"
    assert requests.post(endpoint, json={"token": old, "password": services.password}, timeout=10).status_code == 400

    token_hash = hashlib.sha256(current.encode()).hexdigest()
    services.odb.first_access_tokens.update_one(
        {"token_hash": token_hash}, {"$set": {"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)}}
    )
    assert requests.post(endpoint, json={"token": current, "password": services.password}, timeout=10).status_code == 400

    valid = _issue_invite(services, tid, uid, email, "Valid")
    assert requests.post(endpoint, json={"token": valid, "password": services.password}, timeout=10).status_code == 200
    assert requests.post(endpoint, json={"token": valid, "password": "another-password"}, timeout=10).status_code == 400

    other_tid, _other_uid, _ = _new_tenant_and_user(services, "token-other")
    forged = "cross-tenant-test-token-which-is-long-enough"
    provisioned_id = services.odb.users.find_one({"hub_user_id": uid})["id"]
    services.odb.first_access_tokens.insert_one({
        "token_hash": hashlib.sha256(forged.encode()).hexdigest(),
        "user_id": provisioned_id,
        "restaurant_id": other_tid, "used": False,
        "created_at": datetime.now(timezone.utc),
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
    })
    assert provisioned_id
    assert requests.post(endpoint, json={"token": forged, "password": "safe-password"}, timeout=10).status_code == 400
    services.db.module_user_grants.update_one(
        {"tenant_id": tid, "user_id": uid, "module_key": "orders"}, {"$set": {"active": True}}
    )
    services.call("PATCH", f"/hub/tenants/{tid}", json={"status": "suspended"}).raise_for_status()
    assert requests.post(services.orders + "/api/auth/login", json={"email": email, "password": services.password}, timeout=10).status_code == 403


def test_provisioning_rejects_cross_tenant_user_binding(services):
    tid, uid, _email = _new_tenant_and_user(services, "owner-a")
    assert services.call("POST", f"/hub/tenants/{tid}/modules/orders/activate").status_code == 200
    other_tid, _other_uid, _ = _new_tenant_and_user(services, "owner-b")
    response = requests.post(
        services.orders + "/api/internal/hub/provision",
        headers={"X-Module-Key": services.key},
        json={"tenant_id": other_tid, "tenant_name": "Other", "hub_user_id": uid,
              "name": "Wrong", "email": "wrong@example.com", "role": "admin"}, timeout=10,
    )
    assert response.status_code == 409
    assert services.odb.users.count_documents({"hub_user_id": uid, "restaurant_id": tid}) == 1


def test_failed_provisioning_is_recorded_and_retryable(services):
    tid, uid, _email = _new_tenant_and_user(services, "retry")
    services.stop("orders")
    failed = services.call("POST", f"/hub/tenants/{tid}/modules/orders/activate")
    assert failed.status_code == 503
    state = services.db.tenant_modules.find_one({"tenant_id": tid, "module_key": "orders"})
    assert state["active"] is True and state["provisioning_status"] == "failed"

    orders_env = {**services.env, "DB_NAME": "orders_p0", "JWT_SECRET": "test-only-orders-secret-which-is-long-enough"}
    services.start("orders", [__import__("sys").executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(services.oport)], services.orders_backend, orders_env)
    services.wait(lambda: requests.get(services.orders + "/api/health", timeout=1).raise_for_status(), "orders")
    retried = services.call("POST", f"/hub/tenants/{tid}/modules/orders/activate")
    assert retried.status_code == 200, retried.text
    state = services.db.tenant_modules.find_one({"tenant_id": tid, "module_key": "orders"})
    assert state["provisioning_status"] == "succeeded" and state["provisioned_user_id"] == uid


def test_email_failure_is_recorded_and_retryable(services):
    tid, _uid, _email = _new_tenant_and_user(services, "email-failure")
    original = services.env.get("DACOT_LOCAL_INTEGRATION")
    try:
        services.env.pop("DACOT_LOCAL_INTEGRATION", None)
        services.restart_hub()
        response = services.call("POST", f"/hub/tenants/{tid}/modules/orders/activate")
        assert response.status_code == 503
        state = services.db.tenant_modules.find_one({"tenant_id": tid, "module_key": "orders"})
        assert state["provisioning_status"] == "failed"
        assert state["provisioning_error"] == "email_delivery_failed"
    finally:
        if original is not None:
            services.env["DACOT_LOCAL_INTEGRATION"] = original
        services.restart_hub()
    assert services.call("POST", f"/hub/tenants/{tid}/modules/orders/activate").status_code == 200
