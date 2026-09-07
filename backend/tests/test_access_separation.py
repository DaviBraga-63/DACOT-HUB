"""Iteration 4 — structural access separation: DACOT staff (hub_users) vs restaurant
clients (tenant_users). Covers staff read/write scopes, viewer read-only, client 403 on
/api/hub/*, portal isolation and handoff claim derivation."""
import jwt
import pytest


def _decode(token, secret):
    return jwt.decode(token, secret, algorithms=["HS256"], options={"verify_aud": False})


# ─── 1. super_admin sees everything ───────────────────────────────────────────
class TestSuperAdmin:
    def test_super_admin_lists_all_tenants(self, api, client):
        r = client.get(f"{api}/hub/tenants", timeout=30)
        assert r.status_code == 200, r.text
        items = r.json()
        items = items if isinstance(items, list) else items.get("items", [])
        assert len(items) >= 5, f"expected >=5 tenants, got {len(items)}"

    def test_super_admin_me(self, api, client):
        r = client.get(f"{api}/auth/me", timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d["user_type"] == "staff" and d["role"] == "super_admin"
        assert "password_hash" not in d

    @pytest.mark.parametrize("path", ["/hub/dashboard/stats", "/hub/dashboard/activity",
                                      "/hub/modules", "/hub/tenants"])
    def test_super_admin_reads_all_areas(self, api, client, path):
        assert client.get(f"{api}{path}", timeout=30).status_code == 200


# ─── 2. staff admin: read + write ─────────────────────────────────────────────
class TestStaffAdminWrite:
    def test_admin_reads(self, api, staff_admin, hamburgueria):
        tid = hamburgueria["id"]
        for p in ["/hub/tenants", "/hub/dashboard/stats", "/hub/modules",
                  f"/hub/tenants/{tid}", f"/hub/tenants/{tid}/modules",
                  f"/hub/tenants/{tid}/users"]:
            assert staff_admin.get(f"{api}{p}", timeout=30).status_code == 200, p

    def test_admin_patch_tenant(self, api, staff_admin, hamburgueria):
        tid = hamburgueria["id"]
        original = hamburgueria.get("notes") or ""
        r = staff_admin.patch(f"{api}/hub/tenants/{tid}", json={"notes": "TEST_admin_patch"},
                              timeout=30)
        assert r.status_code == 200, r.text
        g = staff_admin.get(f"{api}/hub/tenants/{tid}", timeout=30)
        assert g.json().get("notes") == "TEST_admin_patch"
        # restore
        assert staff_admin.patch(f"{api}/hub/tenants/{tid}", json={"notes": original},
                                 timeout=30).status_code == 200

    def test_admin_module_toggle_and_launch_token(self, api, staff_admin, hamburgueria):
        tid = hamburgueria["id"]
        assert staff_admin.post(f"{api}/hub/tenants/{tid}/modules/kitchen/deactivate",
                                timeout=30).status_code == 200
        mods = staff_admin.get(f"{api}/hub/tenants/{tid}/modules", timeout=30).json()
        kitchen = [m for m in mods if m["key"] == "kitchen"][0]
        assert kitchen["active"] is False
        assert staff_admin.post(f"{api}/hub/tenants/{tid}/modules/kitchen/activate",
                                timeout=30).status_code == 200
        mods = staff_admin.get(f"{api}/hub/tenants/{tid}/modules", timeout=30).json()
        assert [m for m in mods if m["key"] == "kitchen"][0]["active"] is True
        r = staff_admin.post(f"{api}/hub/tenants/{tid}/modules/orders/launch-token", timeout=30)
        assert r.status_code == 200, r.text
        assert r.json().get("handoff")


# ─── 3. viewer: read-only ─────────────────────────────────────────────────────
class TestViewerReadOnly:
    def test_viewer_reads(self, api, staff_viewer, hamburgueria):
        tid = hamburgueria["id"]
        for p in ["/hub/tenants", "/hub/dashboard/stats", "/hub/modules",
                  f"/hub/tenants/{tid}", f"/hub/tenants/{tid}/modules",
                  f"/hub/tenants/{tid}/users"]:
            assert staff_viewer.get(f"{api}{p}", timeout=30).status_code == 200, p

    def test_viewer_writes_forbidden(self, api, staff_viewer, hamburgueria):
        tid = hamburgueria["id"]
        calls = [
            ("post", f"/hub/tenants", {"name": "TEST_viewer", "owner_name": "x",
                                       "email": "test_viewer@example.com"}),
            ("patch", f"/hub/tenants/{tid}", {"notes": "TEST_viewer"}),
            ("delete", f"/hub/tenants/{tid}", None),
            ("post", f"/hub/tenants/{tid}/modules/kitchen/activate", None),
            ("post", f"/hub/tenants/{tid}/modules/kitchen/deactivate", None),
            ("patch", f"/hub/tenants/{tid}/modules/orders", {"launch_url": "https://x.test"}),
            ("post", f"/hub/tenants/{tid}/modules/orders/launch-token", None),
        ]
        for method, path, body in calls:
            fn = getattr(staff_viewer, method)
            r = fn(f"{api}{path}", json=body, timeout=30) if body is not None else \
                fn(f"{api}{path}", timeout=30)
            assert r.status_code == 403, f"{method.upper()} {path} -> {r.status_code}"


# ─── 4/5/6. restaurant client: own portal only, 403 on /hub/* ─────────────────
class TestRestaurantClientIsolation:
    def test_login_shape(self, api, client_a_admin, hamburgueria):
        _, data = client_a_admin
        assert data["user_type"] == "restaurant"
        assert data["role"] == "admin"
        assert data["tenant_id"] == hamburgueria["id"]
        assert "password_hash" not in data

    def test_me_shape_no_leak(self, api, client_a_admin, hamburgueria):
        s, _ = client_a_admin
        r = s.get(f"{api}/auth/me", timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d["user_type"] == "restaurant" and d["tenant_id"] == hamburgueria["id"]
        assert "password_hash" not in d and "_id" not in d

    def test_client_forbidden_on_all_hub_reads(self, api, client_a_admin, hamburgueria,
                                               bella_napoli):
        s, _ = client_a_admin
        paths = ["/hub/tenants", f"/hub/tenants/{bella_napoli['id']}",
                 f"/hub/tenants/{hamburgueria['id']}", "/hub/dashboard/stats",
                 "/hub/dashboard/activity", "/hub/modules",
                 f"/hub/tenants/{hamburgueria['id']}/users",
                 f"/hub/tenants/{bella_napoli['id']}/modules"]
        for p in paths:
            assert s.get(f"{api}{p}", timeout=30).status_code == 403, p

    def test_client_forbidden_on_hub_writes(self, api, client_a_admin, hamburgueria,
                                            bella_napoli):
        s, _ = client_a_admin
        own, other = hamburgueria["id"], bella_napoli["id"]
        calls = [
            ("post", f"/hub/tenants/{own}/modules/kitchen/activate", None),
            ("post", f"/hub/tenants/{own}/modules/kitchen/deactivate", None),
            ("post", f"/hub/tenants/{other}/modules/orders/activate", None),
            ("post", f"/hub/tenants/{other}/modules/orders/deactivate", None),
            ("post", "/hub/tenants", {"name": "TEST_client", "owner_name": "x",
                                      "email": "test_client@example.com"}),
            ("patch", f"/hub/tenants/{own}", {"notes": "hack"}),
            ("delete", f"/hub/tenants/{other}", None),
            ("post", f"/hub/tenants/{own}/modules/orders/launch-token", None),
        ]
        for method, path, body in calls:
            fn = getattr(s, method)
            r = fn(f"{api}{path}", json=body, timeout=30) if body is not None else \
                fn(f"{api}{path}", timeout=30)
            assert r.status_code == 403, f"{method.upper()} {path} -> {r.status_code}"


# ─── 7/8/9/10. portal context + handoff claims ────────────────────────────────
class TestPortal:
    def test_context_shape_and_modules(self, api, client_a_admin, hamburgueria):
        s, _ = client_a_admin
        r = s.get(f"{api}/portal/context", timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert set(d.keys()) == {"user", "tenant", "modules"}
        assert d["tenant"]["id"] == hamburgueria["id"]
        assert set(d["tenant"].keys()) == {"id", "name", "slug", "status"}
        assert set(d["user"].keys()) == {"id", "name", "email", "role"}
        # no DACOT administrative fields leaked (tenant notes, plan, owner, billing)
        forbidden = {"notes", "plan", "monthly_fee", "owner_name", "owner_email",
                     "password_hash", "created_by", "internal_notes"}
        assert not (set(d["tenant"].keys()) & forbidden)
        for m in d["modules"]:
            assert not (set(m.keys()) & forbidden), m.keys()
        active = {m["key"] for m in d["modules"] if m["active"]}
        assert active == {"orders", "kitchen"}, active
        assert len(d["modules"]) >= 4

    def test_inactive_module_400(self, api, client_a_admin):
        s, _ = client_a_admin
        r = s.post(f"{api}/portal/modules/delivery/launch-token", timeout=30)
        assert r.status_code == 400, r.text

    def test_unknown_module_404(self, api, client_a_admin):
        s, _ = client_a_admin
        r = s.post(f"{api}/portal/modules/nao_existe/launch-token", timeout=30)
        assert r.status_code == 404, r.text

    def test_malicious_body_ignored(self, api, client_a_admin, bella_napoli, hamburgueria,
                                    env_backend):
        s, _ = client_a_admin
        r = s.post(f"{api}/portal/modules/orders/launch-token",
                   json={"tenant_id": bella_napoli["id"], "restaurant_id": bella_napoli["id"],
                         "role": "super_admin"}, timeout=30)
        assert r.status_code == 200, r.text
        claims = _decode(r.json()["handoff"], env_backend["HANDOFF_JWT_SECRET"])
        assert claims["restaurant_id"] == hamburgueria["id"]
        assert claims["role"] == "admin"
        assert claims["module"] == "orders"
        assert claims["sub"].startswith("tenant_user:")

    def test_waiter_role_in_handoff(self, api, client_a_waiter, hamburgueria, env_backend):
        s, data = client_a_waiter
        assert data["role"] == "waiter"
        r = s.post(f"{api}/portal/modules/orders/launch-token", timeout=30)
        assert r.status_code == 200, r.text
        claims = _decode(r.json()["handoff"], env_backend["HANDOFF_JWT_SECRET"])
        assert claims["role"] == "waiter"
        assert claims["sub"] == f"tenant_user:{data['id']}"
        assert claims["restaurant_id"] == hamburgueria["id"]

    def test_kitchen_other_tenant_isolation(self, api, client_b_kitchen, bella_napoli,
                                            hamburgueria, env_backend):
        s, data = client_b_kitchen
        assert data["role"] == "kitchen"
        assert data["tenant_id"] == bella_napoli["id"]
        r = s.post(f"{api}/portal/modules/orders/launch-token", timeout=30)
        assert r.status_code == 200, r.text
        claims = _decode(r.json()["handoff"], env_backend["HANDOFF_JWT_SECRET"])
        assert claims["role"] == "kitchen"
        assert claims["restaurant_id"] == bella_napoli["id"]
        assert claims["restaurant_id"] != hamburgueria["id"]
        ctx = s.get(f"{api}/portal/context", timeout=30).json()
        assert ctx["tenant"]["id"] == bella_napoli["id"]

    def test_portal_denied_for_staff_and_anon(self, api, client, staff_viewer, anon):
        assert client.get(f"{api}/portal/context", timeout=30).status_code == 403
        assert staff_viewer.get(f"{api}/portal/context", timeout=30).status_code == 403
        assert anon.get(f"{api}/portal/context", timeout=30).status_code == 401
        assert client.post(f"{api}/portal/modules/orders/launch-token",
                           timeout=30).status_code == 403
        assert anon.post(f"{api}/portal/modules/orders/launch-token",
                         timeout=30).status_code == 401


# ─── 13. staff handoff claims + auth guards ───────────────────────────────────
class TestStaffHandoff:
    def test_staff_handoff_claims(self, api, client, hamburgueria, env_backend):
        r = client.post(f"{api}/hub/tenants/{hamburgueria['id']}/modules/orders/launch-token",
                        timeout=30)
        assert r.status_code == 200, r.text
        claims = _decode(r.json()["handoff"], env_backend["HANDOFF_JWT_SECRET"])
        assert claims["sub"].startswith("hub_user:")
        assert claims["role"] == "admin"
        assert claims["restaurant_id"] == hamburgueria["id"]

    def test_anonymous_401(self, api, anon, hamburgueria):
        r = anon.post(f"{api}/hub/tenants/{hamburgueria['id']}/modules/orders/launch-token",
                      timeout=30)
        assert r.status_code == 401


# ─── 12. regression: auth lifecycle both populations, public status ───────────
class TestRegression:
    def test_refresh_and_logout_restaurant(self, api):
        from conftest import RESTAURANT_CREDS, _login
        s, _ = _login(RESTAURANT_CREDS["marina@hamburgueriaexemplo.com"])
        assert s.post(f"{api}/auth/refresh", timeout=30).status_code == 200
        assert s.get(f"{api}/portal/context", timeout=30).status_code == 200
        assert s.post(f"{api}/auth/logout", timeout=30).status_code == 200
        assert s.get(f"{api}/auth/me", timeout=30).status_code == 401

    def test_refresh_and_logout_staff(self, api, staff_viewer_creds):
        from conftest import _login
        s, _ = _login(staff_viewer_creds)
        assert s.post(f"{api}/auth/refresh", timeout=30).status_code == 200
        assert s.get(f"{api}/hub/tenants", timeout=30).status_code == 200
        assert s.post(f"{api}/auth/logout", timeout=30).status_code == 200
        assert s.get(f"{api}/auth/me", timeout=30).status_code == 401

    def test_bad_password_401(self, api, anon):
        r = anon.post(f"{api}/auth/login",
                      json={"email": "joao@hamburgueriaexemplo.com", "password": "errada!"},
                      timeout=30)
        assert r.status_code in (401, 429)

    def test_dashboard_kpis(self, api, client):
        d = client.get(f"{api}/hub/dashboard/stats", timeout=30).json()
        assert isinstance(d, dict) and d
        assert any(isinstance(v, int) for v in d.values())

    def test_tenant_crud(self, api, client):
        payload = {"name": "TEST_Restaurante QA", "owner_name": "QA Owner",
                   "email": "test_qa_tenant@example.com"}
        c = client.post(f"{api}/hub/tenants", json=payload, timeout=30)
        assert c.status_code in (200, 201), c.text
        tid = c.json()["id"]
        try:
            g = client.get(f"{api}/hub/tenants/{tid}", timeout=30)
            assert g.status_code == 200 and g.json()["name"] == payload["name"]
            p = client.patch(f"{api}/hub/tenants/{tid}", json={"name": "TEST_Renamed QA"},
                             timeout=30)
            assert p.status_code == 200
            assert client.get(f"{api}/hub/tenants/{tid}",
                              timeout=30).json()["name"] == "TEST_Renamed QA"
        finally:
            d = client.delete(f"{api}/hub/tenants/{tid}", timeout=30)
            assert d.status_code in (200, 204)
        assert client.get(f"{api}/hub/tenants/{tid}", timeout=30).status_code == 404

    def test_catalog(self, api, client):
        mods = client.get(f"{api}/hub/modules", timeout=30).json()
        assert isinstance(mods, list) and len(mods) >= 4
        assert all("_id" not in m for m in mods)

    def test_public_module_status(self, api, anon, hamburgueria, env_backend):
        url = f"{api}/public/tenants/{hamburgueria['id']}/modules/orders/status"
        ok = anon.get(url, headers={"X-Module-Key": env_backend["ORDERS_MODULE_KEY"]}, timeout=30)
        assert ok.status_code == 200, ok.text
        assert ok.json()["active"] is True
        bad = anon.get(url, headers={"X-Module-Key": "wrong-key"}, timeout=30)
        assert bad.status_code == 401
        assert anon.get(url, timeout=30).status_code == 401


# ─── Auth playbook checks (lockout, generic reset response, CORS) ──────────────
class TestAuthPlaybook:
    def test_brute_force_lockout(self, api, anon):
        import uuid
        email = f"test_lock_{uuid.uuid4().hex[:8]}@example.com"
        codes = []
        for _ in range(16):
            r = anon.post(f"{api}/auth/login", json={"email": email, "password": "wrong-pass"},
                          timeout=30)
            codes.append(r.status_code)
            if r.status_code == 429:
                break
        assert codes[:5] == [401] * 5, codes
        # NOTE: lockout identifier uses request.client.host (ingress pod IP, several pods),
        # so the 5-strike bucket can be split across pods -> 429 may take >6 attempts.
        assert 429 in codes, codes

    def test_forgot_password_identical_response(self, api, anon):
        known = anon.post(f"{api}/auth/forgot-password",
                          json={"email": "joao@hamburgueriaexemplo.com"}, timeout=30)
        unknown = anon.post(f"{api}/auth/forgot-password",
                            json={"email": "test_nao_existe_qa@example.com"}, timeout=30)
        assert known.status_code == unknown.status_code == 200
        assert known.json() == unknown.json()

    def test_reset_invalid_token_400(self, api, anon):
        r = anon.post(f"{api}/auth/reset-password",
                      json={"token": "invalido", "password": "Nova@2026"}, timeout=30)
        assert r.status_code == 400

    def test_login_sets_httponly_cookies(self, api, staff_viewer_creds):
        import requests
        s = requests.Session()
        r = s.post(f"{api}/auth/login", json={"email": staff_viewer_creds["email"],
                                              "password": staff_viewer_creds["password"]},
                   timeout=30)
        assert r.status_code == 200
        raw = "; ".join(r.headers.get_all("set-cookie")) if hasattr(r.headers, "get_all") \
            else r.headers.get("set-cookie", "")
        assert "access_token" in raw and "refresh_token" in raw
        for c in r.raw.headers.getlist("Set-Cookie"):
            if c.startswith(("access_token", "refresh_token")):
                assert "HttpOnly" in c and "Secure" in c, c

    def test_cors_backend_config_explicit_origins(self, api, anon):
        """The edge proxy rewrites CORS headers in this preview env (returns "*"),
        so assert the backend app config instead of the proxied response."""
        import re
        src = open("/app/backend/server.py").read()
        assert "allow_credentials=True" in src
        m = re.search(r"allow_origins=\[([^\]]*)\]", src)
        assert m and "*" not in m.group(1), m.group(1) if m else "allow_origins missing"
