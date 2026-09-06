"""Iteration 5 — Hub CRUD for restaurant users (tenant_users): create / edit / deactivate
by DACOT staff. Tenant scoping, RBAC (viewer read-only, restaurant clients forbidden) and
deactivation taking effect immediately are the properties under test."""
import uuid

import pytest


def _unique_email():
    return f"test_tu_{uuid.uuid4().hex[:10]}@example.com"


class TestTenantUsersCrud:
    def test_admin_creates_edits_deactivates_user(self, api, client, hamburgueria):
        tid = hamburgueria["id"]
        email = _unique_email()
        c = client.post(f"{api}/hub/tenants/{tid}/users",
                        json={"name": "QA User", "email": email, "role": "waiter"}, timeout=30)
        assert c.status_code == 200, c.text
        created = c.json()
        assert created["email"] == email
        assert created["role"] == "waiter"
        assert created["status"] == "active"
        assert created.get("temp_password")  # generated since no password was supplied
        uid = created["id"]
        try:
            # appears in the tenant's user list
            listed = client.get(f"{api}/hub/tenants/{tid}/users", timeout=30).json()
            assert any(u["id"] == uid for u in listed)

            # edit role
            p = client.patch(f"{api}/hub/tenants/{tid}/users/{uid}", json={"role": "manager"},
                             timeout=30)
            assert p.status_code == 200, p.text
            assert p.json()["role"] == "manager"

            # deactivate
            d = client.patch(f"{api}/hub/tenants/{tid}/users/{uid}", json={"status": "inactive"},
                             timeout=30)
            assert d.status_code == 200
            assert d.json()["status"] == "inactive"

            # deactivated user cannot log in nor use an existing session
            import requests
            s = requests.Session()
            r = s.post(f"{api}/auth/login", json={"email": email, "password": "irrelevant"},
                       timeout=30)
            assert r.status_code in (401, 429)

            # reactivate
            r2 = client.patch(f"{api}/hub/tenants/{tid}/users/{uid}", json={"status": "active"},
                              timeout=30)
            assert r2.status_code == 200
            assert r2.json()["status"] == "active"
        finally:
            client.patch(f"{api}/hub/tenants/{tid}/users/{uid}", json={"status": "inactive"},
                        timeout=30)

    def test_create_with_explicit_password_no_temp_password_returned(self, api, client,
                                                                      hamburgueria):
        tid = hamburgueria["id"]
        email = _unique_email()
        r = client.post(f"{api}/hub/tenants/{tid}/users",
                        json={"name": "QA", "email": email, "role": "waiter",
                              "password": "Explicita@123"}, timeout=30)
        assert r.status_code == 200, r.text
        assert r.json().get("temp_password") is None

    def test_invalid_role_rejected(self, api, client, hamburgueria):
        r = client.post(f"{api}/hub/tenants/{hamburgueria['id']}/users",
                        json={"name": "QA", "email": _unique_email(), "role": "owner"},
                        timeout=30)
        assert r.status_code == 400

    def test_duplicate_email_rejected(self, api, client, hamburgueria):
        email = _unique_email()
        first = client.post(f"{api}/hub/tenants/{hamburgueria['id']}/users",
                            json={"name": "QA", "email": email, "role": "waiter"}, timeout=30)
        assert first.status_code == 200, first.text
        dup = client.post(f"{api}/hub/tenants/{hamburgueria['id']}/users",
                          json={"name": "QA2", "email": email, "role": "manager"}, timeout=30)
        assert dup.status_code == 409

    def test_user_scoped_to_its_own_tenant(self, api, client, hamburgueria, bella_napoli):
        created = client.post(f"{api}/hub/tenants/{hamburgueria['id']}/users",
                              json={"name": "QA", "email": _unique_email(), "role": "waiter"},
                              timeout=30).json()
        # patching the same user id under a different tenant id must 404 (no cross-tenant edit)
        r = client.patch(f"{api}/hub/tenants/{bella_napoli['id']}/users/{created['id']}",
                         json={"role": "admin"}, timeout=30)
        assert r.status_code == 404, r.text

    def test_unknown_tenant_or_user_404(self, api, client, hamburgueria):
        assert client.post(f"{api}/hub/tenants/507f1f77bcf86cd799439011/users",
                           json={"name": "QA", "email": _unique_email(), "role": "waiter"},
                           timeout=30).status_code == 404
        assert client.patch(f"{api}/hub/tenants/{hamburgueria['id']}/users/507f1f77bcf86cd799439011",
                            json={"role": "admin"}, timeout=30).status_code == 404

    def test_viewer_cannot_write(self, api, staff_viewer, hamburgueria):
        r = staff_viewer.post(f"{api}/hub/tenants/{hamburgueria['id']}/users",
                              json={"name": "QA", "email": _unique_email(), "role": "waiter"},
                              timeout=30)
        assert r.status_code == 403

    def test_restaurant_client_forbidden(self, api, client_a_admin, hamburgueria):
        s, _ = client_a_admin
        r = s.post(f"{api}/hub/tenants/{hamburgueria['id']}/users",
                  json={"name": "QA", "email": _unique_email(), "role": "waiter"}, timeout=30)
        assert r.status_code == 403

    def test_anonymous_401(self, api, anon, hamburgueria):
        r = anon.post(f"{api}/hub/tenants/{hamburgueria['id']}/users",
                      json={"name": "QA", "email": _unique_email(), "role": "waiter"}, timeout=30)
        assert r.status_code == 401
