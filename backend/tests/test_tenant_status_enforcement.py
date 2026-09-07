"""Iteration 7 — tenant.status enforcement (audit Task 2).

A tenant is operational only in "active"/"trial". "suspended"/"inactive"
must block: restaurant login, the portal (even for an already-open
session — not just at login time), and handoff generation into an
external module (both the portal-issued and the staff-issued paths).
Staff must keep full administrative access to the tenant regardless of
its status (view/edit/toggle modules/manage users) — only the tenant's
own operational access is gated.

Everything here creates and tears down its own throwaway tenant/user —
it does not depend on any seeded tenant's status.
"""
import uuid

import pytest


def _unique_email():
    return f"test_status_{uuid.uuid4().hex[:10]}@example.com"


@pytest.fixture
def status_tenant(api, client):
    """A fresh tenant with 'orders' active and one login-capable waiter,
    created as 'active'. Cleaned up (tenant + user cascade) after the test."""
    email = _unique_email()
    password = "Explicita@123"

    t = client.post(f"{api}/hub/tenants",
                    json={"name": "TEST_Status Tenant", "owner_name": "QA",
                          "email": f"test_status_owner_{uuid.uuid4().hex[:8]}@example.com",
                          "status": "active"},
                    timeout=30)
    assert t.status_code == 200, t.text
    tenant = t.json()
    tid = tenant["id"]

    a = client.post(f"{api}/hub/tenants/{tid}/modules/orders/activate", timeout=30)
    assert a.status_code == 200, a.text

    u = client.post(f"{api}/hub/tenants/{tid}/users",
                    json={"name": "QA Waiter", "email": email, "role": "waiter", "password": password},
                    timeout=30)
    assert u.status_code == 200, u.text

    yield {"tid": tid, "slug": tenant["slug"], "email": email, "password": password}

    client.delete(f"{api}/hub/tenants/{tid}", timeout=30)


def _set_status(api, client, tid, status):
    r = client.patch(f"{api}/hub/tenants/{tid}", json={"status": status}, timeout=30)
    assert r.status_code == 200, r.text


def _login(api, email, password):
    import requests
    s = requests.Session()
    r = s.post(f"{api}/auth/login", json={"email": email, "password": password}, timeout=30)
    return s, r


class TestLoginGatedByTenantStatus:
    @pytest.mark.parametrize("status", ["active", "trial"])
    def test_login_succeeds_when_tenant_operational(self, api, client, status_tenant, status):
        _set_status(api, client, status_tenant["tid"], status)
        s, r = _login(api, status_tenant["email"], status_tenant["password"])
        assert r.status_code == 200, r.text
        assert r.json()["tenant_id"] == status_tenant["tid"]

    @pytest.mark.parametrize("status", ["suspended", "inactive"])
    def test_login_rejected_when_tenant_not_operational(self, api, client, status_tenant, status):
        _set_status(api, client, status_tenant["tid"], status)
        s, r = _login(api, status_tenant["email"], status_tenant["password"])
        assert r.status_code == 401, r.text
        # generic message — must not reveal *why* (tenant status) to the caller
        assert "inválid" in r.json().get("detail", "").lower()


class TestPortalGatedByTenantStatus:
    @pytest.mark.parametrize("status", ["active", "trial"])
    def test_portal_and_handoff_work_when_operational(self, api, client, status_tenant, status):
        _set_status(api, client, status_tenant["tid"], status)
        s, r = _login(api, status_tenant["email"], status_tenant["password"])
        assert r.status_code == 200, r.text

        ctx = s.get(f"{api}/portal/context", timeout=30)
        assert ctx.status_code == 200, ctx.text
        assert ctx.json()["tenant"]["status"] == status

        lt = s.post(f"{api}/portal/modules/orders/launch-token", timeout=30)
        assert lt.status_code == 200, lt.text
        assert lt.json().get("handoff")

    @pytest.mark.parametrize("status", ["suspended", "inactive"])
    def test_already_open_session_is_locked_out_when_tenant_becomes_non_operational(
            self, api, client, status_tenant, status):
        """The session is opened while the tenant is still active — enforcement
        must happen on every portal request, not just at login."""
        s, r = _login(api, status_tenant["email"], status_tenant["password"])
        assert r.status_code == 200, r.text
        assert s.get(f"{api}/portal/context", timeout=30).status_code == 200

        _set_status(api, client, status_tenant["tid"], status)

        ctx = s.get(f"{api}/portal/context", timeout=30)
        assert ctx.status_code == 403, ctx.text

        lt = s.post(f"{api}/portal/modules/orders/launch-token", timeout=30)
        assert lt.status_code == 403, lt.text


class TestStaffHandoffGatedByTenantStatus:
    @pytest.mark.parametrize("status", ["active", "trial"])
    def test_staff_handoff_works_when_operational(self, api, client, status_tenant, status):
        _set_status(api, client, status_tenant["tid"], status)
        r = client.post(f"{api}/hub/tenants/{status_tenant['tid']}/modules/orders/launch-token",
                        timeout=30)
        assert r.status_code == 200, r.text
        assert r.json().get("handoff")

    @pytest.mark.parametrize("status", ["suspended", "inactive"])
    def test_staff_handoff_blocked_when_not_operational(self, api, client, status_tenant, status):
        _set_status(api, client, status_tenant["tid"], status)
        r = client.post(f"{api}/hub/tenants/{status_tenant['tid']}/modules/orders/launch-token",
                        timeout=30)
        assert r.status_code == 400, r.text


class TestStaffAdministrationUnaffectedByTenantStatus:
    @pytest.mark.parametrize("status", ["suspended", "inactive"])
    def test_staff_can_still_manage_a_non_operational_tenant(self, api, client, status_tenant, status):
        tid = status_tenant["tid"]
        _set_status(api, client, tid, status)

        assert client.get(f"{api}/hub/tenants/{tid}", timeout=30).status_code == 200
        assert client.get(f"{api}/hub/tenants/{tid}/modules", timeout=30).status_code == 200
        assert client.get(f"{api}/hub/tenants/{tid}/users", timeout=30).status_code == 200

        p = client.patch(f"{api}/hub/tenants/{tid}", json={"notes": "still editable"}, timeout=30)
        assert p.status_code == 200, p.text

        deact = client.post(f"{api}/hub/tenants/{tid}/modules/orders/deactivate", timeout=30)
        assert deact.status_code == 200, deact.text
        react = client.post(f"{api}/hub/tenants/{tid}/modules/orders/activate", timeout=30)
        assert react.status_code == 200, react.text

        # reactivating the tenant restores operational access immediately
        _set_status(api, client, tid, "active")
        s, r = _login(api, status_tenant["email"], status_tenant["password"])
        assert r.status_code == 200, r.text
        assert s.get(f"{api}/portal/context", timeout=30).status_code == 200
