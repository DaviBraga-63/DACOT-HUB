"""Iteration 2 — Module handoff (launch-token) + public module status + light regression."""
import time

import jwt
import pytest
import requests


# ─── launch-token ─────────────────────────────────────────────────────────────
class TestLaunchToken:
    def test_launch_token_success_and_claims(self, api, client, hamburgueria, env_backend):
        tid = hamburgueria["id"]
        # ensure orders active
        mods = client.get(f"{api}/hub/tenants/{tid}/modules", timeout=30).json()
        orders = [m for m in mods
                  if m.get("module_key") == "orders" or m.get("key") == "orders"][0]
        assert orders.get("active") is True, f"orders not active: {orders}"

        me = client.get(f"{api}/auth/me", timeout=30).json()
        admin_id = me.get("id") or me.get("_id") or me.get("user", {}).get("id")

        r = client.post(f"{api}/hub/tenants/{tid}/modules/orders/launch-token", json={}, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["expires_in"] == 60
        assert d["jti"]
        assert d["launch_url"].startswith("http")
        token = d["handoff"]
        assert len(token.split(".")) == 3

        secret = env_backend["HANDOFF_JWT_SECRET"]
        claims = jwt.decode(token, secret, algorithms=["HS256"], audience="dacot-orders",
                            issuer="dacot-hub")
        assert claims["iss"] == "dacot-hub"
        assert claims["aud"] == "dacot-orders"
        assert claims["sub"] == f"hub_user:{admin_id}"
        assert claims["restaurant_id"] == tid
        assert len(claims["restaurant_id"]) == 24
        assert claims["restaurant_slug"] == hamburgueria["slug"]
        assert claims["role"] == "admin"
        assert claims["module"] == "orders"
        assert claims["jti"] == d["jti"]
        assert claims["exp"] - claims["iat"] == 60
        assert claims["handoff_version"] == 1
        assert claims["nbf"] <= claims["iat"]
        # secret never leaked in response body
        assert secret not in r.text

    def test_launch_token_rejects_invalid_signature(self, api, client, hamburgueria):
        r = client.post(f"{api}/hub/tenants/{hamburgueria['id']}/modules/orders/launch-token",
                        json={}, timeout=30)
        token = r.json()["handoff"]
        with pytest.raises(jwt.InvalidSignatureError):
            jwt.decode(token, "wrong-secret-value-0000000000000000", algorithms=["HS256"],
                       audience="dacot-orders")

    def test_role_from_frontend_not_authoritative(self, api, client, hamburgueria, env_backend):
        r = client.post(f"{api}/hub/tenants/{hamburgueria['id']}/modules/orders/launch-token",
                        json={"role": "owner"}, timeout=30)
        assert r.status_code == 200, r.text
        claims = jwt.decode(r.json()["handoff"], env_backend["HANDOFF_JWT_SECRET"],
                            algorithms=["HS256"], audience="dacot-orders")
        assert claims["role"] == "admin"

    def test_role_whitelisted_value_accepted(self, api, client, hamburgueria, env_backend):
        r = client.post(f"{api}/hub/tenants/{hamburgueria['id']}/modules/orders/launch-token",
                        json={"role": "waiter"}, timeout=30)
        assert r.status_code == 200, r.text
        claims = jwt.decode(r.json()["handoff"], env_backend["HANDOFF_JWT_SECRET"],
                            algorithms=["HS256"], audience="dacot-orders")
        assert claims["role"] == "waiter"

    def test_module_not_active_returns_400(self, api, client, hamburgueria):
        r = client.post(f"{api}/hub/tenants/{hamburgueria['id']}/modules/delivery/launch-token",
                        json={}, timeout=30)
        assert r.status_code == 400, f"{r.status_code} {r.text}"

    def test_module_in_dev_never_activated_returns_400(self, api, client, hamburgueria):
        r = client.post(f"{api}/hub/tenants/{hamburgueria['id']}/modules/finance/launch-token",
                        json={}, timeout=30)
        assert r.status_code == 400, f"{r.status_code} {r.text}"

    def test_tenant_not_found_404(self, api, client):
        r = client.post(f"{api}/hub/tenants/507f1f77bcf86cd799439011/modules/orders/launch-token",
                        json={}, timeout=30)
        assert r.status_code == 404
        r2 = client.post(f"{api}/hub/tenants/not-an-objectid/modules/orders/launch-token",
                         json={}, timeout=30)
        assert r2.status_code == 404

    def test_unknown_module_404(self, api, client, hamburgueria):
        r = client.post(f"{api}/hub/tenants/{hamburgueria['id']}/modules/nope/launch-token",
                        json={}, timeout=30)
        assert r.status_code == 404

    def test_unauthenticated_401(self, api, anon, hamburgueria):
        r = anon.post(f"{api}/hub/tenants/{hamburgueria['id']}/modules/orders/launch-token",
                      json={}, timeout=30)
        assert r.status_code == 401, f"{r.status_code} {r.text}"

    def test_jti_unique_per_call(self, api, client, hamburgueria):
        a = client.post(f"{api}/hub/tenants/{hamburgueria['id']}/modules/orders/launch-token",
                        json={}, timeout=30).json()["jti"]
        b = client.post(f"{api}/hub/tenants/{hamburgueria['id']}/modules/orders/launch-token",
                        json={}, timeout=30).json()["jti"]
        assert a != b

    def test_activity_log_records_launch_token(self, api, client, hamburgueria):
        client.post(f"{api}/hub/tenants/{hamburgueria['id']}/modules/orders/launch-token",
                    json={}, timeout=30)
        time.sleep(1)
        r = client.get(f"{api}/hub/dashboard/activity", timeout=30)
        assert r.status_code == 200
        actions = [a["action"] for a in r.json()]
        assert "module.launch_token_issued" in actions, actions[:10]


# ─── public module status ─────────────────────────────────────────────────────
class TestPublicModuleStatus:
    def test_no_key_401(self, api, anon, hamburgueria):
        r = anon.get(f"{api}/public/tenants/{hamburgueria['id']}/modules/orders/status", timeout=30)
        assert r.status_code == 401, f"{r.status_code} {r.text}"

    def test_wrong_key_401(self, api, anon, hamburgueria):
        r = anon.get(f"{api}/public/tenants/{hamburgueria['id']}/modules/orders/status",
                     headers={"X-Module-Key": "deadbeef" * 4}, timeout=30)
        assert r.status_code == 401

    def test_correct_key_active_true(self, api, anon, hamburgueria, env_backend):
        r = anon.get(f"{api}/public/tenants/{hamburgueria['id']}/modules/orders/status",
                     headers={"X-Module-Key": env_backend["ORDERS_MODULE_KEY"]}, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["active"] is True
        assert d["module"] == "orders"
        assert d.get("activated_at")
        # no admin data exposure
        for leak in ("owner_name", "email", "phone", "owner_email", "name", "_id"):
            assert leak not in d, f"leaked {leak}: {d}"

    def test_tenant_not_found_404_before_key_check(self, api, anon):
        r = anon.get(f"{api}/public/tenants/507f1f77bcf86cd799439011/modules/orders/status",
                     timeout=30)
        assert r.status_code == 404, f"{r.status_code} {r.text}"

    def test_unknown_module_404(self, api, anon, hamburgueria):
        r = anon.get(f"{api}/public/tenants/{hamburgueria['id']}/modules/nope/status", timeout=30)
        assert r.status_code == 404

    def test_module_without_configured_key_401(self, api, anon, hamburgueria, env_backend):
        r = anon.get(f"{api}/public/tenants/{hamburgueria['id']}/modules/delivery/status",
                     headers={"X-Module-Key": env_backend["ORDERS_MODULE_KEY"]}, timeout=30)
        assert r.status_code == 401


# ─── regression ───────────────────────────────────────────────────────────────
class TestRegression:
    def test_login_and_me(self, api, client, test_credentials):
        r = client.get(f"{api}/auth/me", timeout=30)
        assert r.status_code == 200
        assert r.json()["email"] == test_credentials["email"]

    def test_login_wrong_password_401(self, api, test_credentials):
        r = requests.post(f"{api}/auth/login",
                          json={"email": test_credentials["email"], "password": "Errada@123"},
                          timeout=30)
        assert r.status_code == 401

    def test_dashboard_stats(self, api, client):
        r = client.get(f"{api}/hub/dashboard/stats", timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d["total_tenants"] >= 5
        assert isinstance(d.get("per_module"), list)

    def test_modules_catalog(self, api, client):
        r = client.get(f"{api}/hub/modules", timeout=30)
        assert r.status_code == 200
        keys = {m["key"] for m in r.json()}
        assert {"orders", "kitchen", "delivery"} <= keys

    def test_tenant_crud(self, api, client):
        payload = {"name": "TEST_Handoff Tenant", "slug": "test-handoff-tenant",
                   "owner_name": "QA", "email": "qa_handoff@test.dev", "phone": "11999999999",
                   "status": "trial"}
        r = client.post(f"{api}/hub/tenants", json=payload, timeout=30)
        assert r.status_code in (200, 201), r.text
        tid = r.json()["id"]
        try:
            g = client.get(f"{api}/hub/tenants/{tid}", timeout=30)
            assert g.status_code == 200
            assert g.json()["name"] == payload["name"]

            p = client.patch(f"{api}/hub/tenants/{tid}", json={"status": "active"}, timeout=30)
            assert p.status_code == 200
            assert client.get(f"{api}/hub/tenants/{tid}", timeout=30).json()["status"] == "active"

            # activate/deactivate kitchen + launch-token round trip
            a = client.post(f"{api}/hub/tenants/{tid}/modules/kitchen/activate", timeout=30)
            assert a.status_code == 200, a.text
            lt = client.post(f"{api}/hub/tenants/{tid}/modules/kitchen/launch-token",
                             json={}, timeout=30)
            assert lt.status_code == 200, lt.text
            import jwt as _jwt
            from dotenv import dotenv_values
            secret = dotenv_values("/app/backend/.env")["HANDOFF_JWT_SECRET"]
            c = _jwt.decode(lt.json()["handoff"], secret, algorithms=["HS256"],
                            audience="dacot-kitchen")
            assert c["module"] == "kitchen" and c["restaurant_id"] == tid

            d = client.post(f"{api}/hub/tenants/{tid}/modules/kitchen/deactivate", timeout=30)
            assert d.status_code == 200
            lt2 = client.post(f"{api}/hub/tenants/{tid}/modules/kitchen/launch-token",
                              json={}, timeout=30)
            assert lt2.status_code == 400
        finally:
            dl = client.delete(f"{api}/hub/tenants/{tid}", timeout=30)
            assert dl.status_code in (200, 204)
            assert client.get(f"{api}/hub/tenants/{tid}", timeout=30).status_code == 404
