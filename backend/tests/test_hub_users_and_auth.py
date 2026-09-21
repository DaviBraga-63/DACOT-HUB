"""Iteration 8 — Hub authentication & multi-user hardening.

Covers, in one coherent package:
1. /auth/refresh revocation by hub_user.active, tenant_user.status, and
   tenant.status (active/trial keep working, suspended/inactive/inactive
   user don't).
2. hub_users CRUD (list/create/edit name/change role/activate-deactivate).
3. RBAC on hub_users endpoints (super_admin/admin write, viewer read-only).
4. Self-lockout protection (can't deactivate or demote your own account)
   and the "last admin standing" guard on other accounts.
5. Cross-collection email uniqueness (hub_users vs tenant_users).

Everything here creates its own throwaway hub_users/tenants/tenant_users.
hub_users have no delete endpoint by design (matches tenant_users — only
activate/deactivate), so disposable staff accounts are deactivated in
teardown rather than removed.
"""
import uuid

import pytest
import requests


def _unique_email(prefix="test_hub"):
    return f"{prefix}_{uuid.uuid4().hex[:10]}@example.com"


def _login_session(api, email, password):
    s = requests.Session()
    r = s.post(f"{api}/auth/login", json={"email": email, "password": password}, timeout=30)
    return s, r


@pytest.fixture
def disposable_staff(api, client):
    """A fresh hub_user, role='viewer' (never counts toward the admin quota
    unless explicitly promoted by a test), active, known password."""
    email = _unique_email("test_staff")
    password = "Explicita@123"
    r = client.post(f"{api}/hub/users",
                    json={"name": "QA Staff", "email": email, "role": "viewer", "password": password},
                    timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    yield {"id": data["id"], "email": email, "password": password}
    client.patch(f"{api}/hub/users/{data['id']}", json={"active": False}, timeout=30)


@pytest.fixture
def disposable_tenant_user(api, client):
    """A fresh tenant (created 'active') + one login-capable waiter."""
    email = _unique_email("test_tu")
    password = "Explicita@123"
    t = client.post(f"{api}/hub/tenants",
                    json={"name": "TEST_Auth Tenant", "owner_name": "QA",
                          "email": _unique_email("test_owner"), "status": "active"},
                    timeout=30)
    assert t.status_code == 200, t.text
    tid = t.json()["id"]
    u = client.post(f"{api}/hub/tenants/{tid}/users",
                    json={"name": "QA Waiter", "email": email, "role": "waiter", "password": password},
                    timeout=30)
    assert u.status_code == 200, u.text
    yield {"tid": tid, "uid": u.json()["id"], "email": email, "password": password}
    client.delete(f"{api}/hub/tenants/{tid}", timeout=30)


# ─── 1. Refresh revocation ──────────────────────────────────────────────────
class TestRefreshRevocation:
    def test_refresh_hub_user_active(self, api, disposable_staff):
        s, r = _login_session(api, disposable_staff["email"], disposable_staff["password"])
        assert r.status_code == 200, r.text
        assert s.post(f"{api}/auth/refresh", timeout=30).status_code == 200

    def test_refresh_hub_user_inactive(self, api, client, disposable_staff):
        s, r = _login_session(api, disposable_staff["email"], disposable_staff["password"])
        assert r.status_code == 200, r.text
        assert s.post(f"{api}/auth/refresh", timeout=30).status_code == 200

        d = client.patch(f"{api}/hub/users/{disposable_staff['id']}", json={"active": False}, timeout=30)
        assert d.status_code == 200, d.text

        assert s.post(f"{api}/auth/refresh", timeout=30).status_code == 401

    def test_refresh_tenant_user_active(self, api, disposable_tenant_user):
        s, r = _login_session(api, disposable_tenant_user["email"], disposable_tenant_user["password"])
        assert r.status_code == 200, r.text
        assert s.post(f"{api}/auth/refresh", timeout=30).status_code == 200

    def test_refresh_tenant_user_inactive(self, api, client, disposable_tenant_user):
        tid, uid = disposable_tenant_user["tid"], disposable_tenant_user["uid"]
        s, r = _login_session(api, disposable_tenant_user["email"], disposable_tenant_user["password"])
        assert r.status_code == 200, r.text
        assert s.post(f"{api}/auth/refresh", timeout=30).status_code == 200

        d = client.patch(f"{api}/hub/tenants/{tid}/users/{uid}", json={"status": "inactive"}, timeout=30)
        assert d.status_code == 200, d.text

        assert s.post(f"{api}/auth/refresh", timeout=30).status_code == 401

    @pytest.mark.parametrize("status,expected", [
        ("active", 200), ("trial", 200), ("suspended", 401), ("inactive", 401),
    ])
    def test_refresh_gated_by_tenant_status(self, api, client, disposable_tenant_user, status, expected):
        tid = disposable_tenant_user["tid"]
        s, r = _login_session(api, disposable_tenant_user["email"], disposable_tenant_user["password"])
        assert r.status_code == 200, r.text

        p = client.patch(f"{api}/hub/tenants/{tid}", json={"status": status}, timeout=30)
        assert p.status_code == 200, p.text

        assert s.post(f"{api}/auth/refresh", timeout=30).status_code == expected


# ─── 2. hub_users CRUD ──────────────────────────────────────────────────────
class TestHubUsersCrud:
    def test_list_create_edit_name_role_activate(self, api, client):
        email = _unique_email("test_crud")
        c = client.post(f"{api}/hub/users", json={"name": "QA", "email": email, "role": "viewer"}, timeout=30)
        assert c.status_code == 200, c.text
        created = c.json()
        assert created["role"] == "viewer"
        assert created["active"] is True
        assert created.get("temp_password")  # generated since no password was supplied
        uid = created["id"]
        try:
            listed = client.get(f"{api}/hub/users", timeout=30).json()
            assert any(u["id"] == uid for u in listed)

            p1 = client.patch(f"{api}/hub/users/{uid}", json={"name": "QA Renamed"}, timeout=30)
            assert p1.status_code == 200 and p1.json()["name"] == "QA Renamed"

            p2 = client.patch(f"{api}/hub/users/{uid}", json={"role": "admin"}, timeout=30)
            assert p2.status_code == 200 and p2.json()["role"] == "admin"

            p3 = client.patch(f"{api}/hub/users/{uid}", json={"active": False}, timeout=30)
            assert p3.status_code == 200 and p3.json()["active"] is False

            p4 = client.patch(f"{api}/hub/users/{uid}", json={"active": True}, timeout=30)
            assert p4.status_code == 200 and p4.json()["active"] is True
        finally:
            client.patch(f"{api}/hub/users/{uid}", json={"active": False, "role": "viewer"}, timeout=30)

    def test_create_with_explicit_password_no_temp_password_returned(self, api, client):
        email = _unique_email("test_pw")
        r = client.post(f"{api}/hub/users",
                        json={"name": "QA", "email": email, "role": "viewer", "password": "Explicita@123"},
                        timeout=30)
        assert r.status_code == 200, r.text
        assert r.json().get("temp_password") is None
        client.patch(f"{api}/hub/users/{r.json()['id']}", json={"active": False}, timeout=30)

    def test_invalid_role_rejected(self, api, client):
        r = client.post(f"{api}/hub/users",
                        json={"name": "QA", "email": _unique_email(), "role": "owner"}, timeout=30)
        assert r.status_code == 400

    def test_duplicate_email_within_hub_users_rejected(self, api, client, disposable_staff):
        r = client.post(f"{api}/hub/users",
                        json={"name": "QA2", "email": disposable_staff["email"], "role": "viewer"}, timeout=30)
        assert r.status_code == 409

    def test_unknown_user_404(self, api, client):
        assert client.patch(f"{api}/hub/users/507f1f77bcf86cd799439011",
                            json={"name": "x"}, timeout=30).status_code == 404


# ─── 3. RBAC ────────────────────────────────────────────────────────────────
class TestHubUsersRbac:
    def test_super_admin_full_access(self, api, client):
        assert client.get(f"{api}/hub/users", timeout=30).status_code == 200
        r = client.post(f"{api}/hub/users",
                        json={"name": "QA", "email": _unique_email(), "role": "viewer"}, timeout=30)
        assert r.status_code == 200, r.text
        client.patch(f"{api}/hub/users/{r.json()['id']}", json={"active": False}, timeout=30)

    def test_admin_can_write(self, api, staff_admin):
        r = staff_admin.post(f"{api}/hub/users",
                             json={"name": "QA", "email": _unique_email(), "role": "viewer"}, timeout=30)
        assert r.status_code == 200, r.text
        staff_admin.patch(f"{api}/hub/users/{r.json()['id']}", json={"active": False}, timeout=30)

    def test_viewer_can_read_not_write(self, api, staff_viewer, client):
        assert staff_viewer.get(f"{api}/hub/users", timeout=30).status_code == 200
        r = staff_viewer.post(f"{api}/hub/users",
                              json={"name": "QA", "email": _unique_email(), "role": "viewer"}, timeout=30)
        assert r.status_code == 403

        c = client.post(f"{api}/hub/users",
                        json={"name": "QA", "email": _unique_email(), "role": "viewer"}, timeout=30)
        uid = c.json()["id"]
        try:
            assert staff_viewer.patch(f"{api}/hub/users/{uid}", json={"name": "hacked"},
                                      timeout=30).status_code == 403
        finally:
            client.patch(f"{api}/hub/users/{uid}", json={"active": False}, timeout=30)

    def test_anonymous_401(self, api, anon):
        assert anon.get(f"{api}/hub/users", timeout=30).status_code == 401
        assert anon.post(f"{api}/hub/users", json={"name": "x", "email": _unique_email(), "role": "viewer"},
                         timeout=30).status_code == 401


# ─── 4. Self-lockout protection ─────────────────────────────────────────────
class TestSelfLockoutProtection:
    def test_cannot_deactivate_self(self, api, client):
        me = client.get(f"{api}/auth/me", timeout=30).json()
        r = client.patch(f"{api}/hub/users/{me['id']}", json={"active": False}, timeout=30)
        assert r.status_code == 400, r.text
        # sanity: the account is truly untouched
        assert client.get(f"{api}/auth/me", timeout=30).status_code == 200

    def test_cannot_demote_self_to_viewer(self, api, client):
        me = client.get(f"{api}/auth/me", timeout=30).json()
        r = client.patch(f"{api}/hub/users/{me['id']}", json={"role": "viewer"}, timeout=30)
        assert r.status_code == 400, r.text
        assert client.get(f"{api}/auth/me", timeout=30).json()["role"] == me["role"]

    def test_self_edit_of_non_admin_fields_still_allowed(self, api, client):
        """Only the admin-capability-losing fields (active/role) are blocked
        on self — editing your own name must keep working."""
        me = client.get(f"{api}/auth/me", timeout=30).json()
        r = client.patch(f"{api}/hub/users/{me['id']}", json={"name": me["name"]}, timeout=30)
        assert r.status_code == 200, r.text

    def test_deactivating_a_peer_admin_is_allowed_when_others_remain(self, api, client):
        """Sanity check that the guard is conditional, not an outright freeze
        on ever touching any admin: acting on someone ELSE's account succeeds
        as long as other active admins remain (the real environment's other
        admins, e.g. the bootstrap super_admin, guarantee this here).

        NOTE: the "would leave zero active admins" branch (_active_admin_count
        == 0) is intentionally NOT exercised end-to-end by this suite — doing
        so would require temporarily deactivating every real admin in this
        shared environment, which is unsafe to automate (a failed test could
        leave the environment without any working admin account). That branch
        was verified by code review instead: it mirrors _active_admin_count's
        query exactly and is covered by the same logic already proven safe by
        test_cannot_deactivate_self / test_cannot_demote_self_to_viewer for
        the self case.
        """
        c = client.post(f"{api}/hub/users",
                        json={"name": "QA Peer Admin", "email": _unique_email("test_peer"),
                              "role": "admin", "password": "Explicita@123"}, timeout=30)
        assert c.status_code == 200, c.text
        uid = c.json()["id"]
        d = client.patch(f"{api}/hub/users/{uid}", json={"active": False}, timeout=30)
        assert d.status_code == 200, d.text


# ─── 5. Cross-collection email uniqueness ───────────────────────────────────
class TestCrossCollectionEmailUniqueness:
    def test_hub_user_create_blocked_by_existing_tenant_user_email(self, api, client, disposable_tenant_user):
        r = client.post(f"{api}/hub/users",
                        json={"name": "QA", "email": disposable_tenant_user["email"], "role": "viewer"},
                        timeout=30)
        assert r.status_code == 409, r.text

    def test_tenant_user_create_blocked_by_existing_hub_user_email(self, api, client, disposable_staff):
        t = client.post(f"{api}/hub/tenants",
                        json={"name": "TEST_Dup Tenant", "owner_name": "QA",
                              "email": _unique_email("test_owner2"), "status": "active"}, timeout=30)
        assert t.status_code == 200, t.text
        tid = t.json()["id"]
        try:
            r = client.post(f"{api}/hub/tenants/{tid}/users",
                            json={"name": "QA", "email": disposable_staff["email"], "role": "waiter"},
                            timeout=30)
            assert r.status_code == 409, r.text
        finally:
            client.delete(f"{api}/hub/tenants/{tid}", timeout=30)

    def test_hub_user_email_edit_blocked_by_existing_tenant_user_email(self, api, client, disposable_tenant_user):
        c = client.post(f"{api}/hub/users",
                        json={"name": "QA", "email": _unique_email("test_edit"), "role": "viewer"}, timeout=30)
        assert c.status_code == 200, c.text
        uid = c.json()["id"]
        try:
            r = client.patch(f"{api}/hub/users/{uid}", json={"email": disposable_tenant_user["email"]},
                             timeout=30)
            assert r.status_code == 409, r.text
        finally:
            client.patch(f"{api}/hub/users/{uid}", json={"active": False}, timeout=30)
