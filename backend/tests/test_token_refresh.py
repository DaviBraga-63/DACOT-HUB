"""Iteration 3 — silent token refresh flow (expired access_token + valid refresh_token).

Mirrors the frontend axios interceptor contract in /app/frontend/src/lib/api.js:
401 on a protected route -> POST /api/auth/refresh -> retry original request.
Backend was NOT changed in this fix; these tests pin the server-side contract.
"""
import datetime

import jwt
import pytest
import requests


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _forge(secret, **overrides):
    payload = {"sub": overrides.pop("sub"), "ver": overrides.pop("ver", 0)}
    payload.update(overrides)
    return jwt.encode(payload, secret, algorithm="HS256")


@pytest.fixture(scope="class")
def admin_id(api, client):
    me = client.get(f"{api}/auth/me", timeout=30).json()
    return me["id"]


@pytest.fixture(scope="class")
def jwt_secret(env_backend):
    return env_backend["JWT_SECRET"]


# ─── refresh contract ─────────────────────────────────────────────────────────
class TestTokenRefresh:
    def test_expired_access_returns_401_token_expirado(self, api, admin_id, jwt_secret):
        s = requests.Session()
        s.cookies.set("access_token", _forge(
            jwt_secret, sub=admin_id, email="x@y.z", type="access",
            exp=int((_now() - datetime.timedelta(minutes=1)).timestamp())))
        r = s.get(f"{api}/auth/me", timeout=30)
        assert r.status_code == 401
        assert "expirado" in r.json().get("detail", "").lower()

    def test_expired_access_valid_refresh_recovers(self, api, admin_id, jwt_secret,
                                                   test_credentials):
        s = requests.Session()
        s.cookies.set("access_token", _forge(
            jwt_secret, sub=admin_id, email=test_credentials["email"], type="access",
            exp=int((_now() - datetime.timedelta(minutes=1)).timestamp())))
        s.cookies.set("refresh_token", _forge(
            jwt_secret, sub=admin_id, type="refresh",
            exp=int((_now() + datetime.timedelta(days=6)).timestamp())))

        # 1) protected call fails
        assert s.get(f"{api}/auth/me", timeout=30).status_code == 401

        # 2) refresh succeeds and rotates the access cookie
        old_access = [c.value for c in s.cookies if c.name == "access_token"][0]
        r = s.post(f"{api}/auth/refresh", timeout=30)
        assert r.status_code == 200, r.text
        set_cookie = r.headers.get("Set-Cookie", "")
        assert "access_token=" in set_cookie
        new_access = set_cookie.split("access_token=")[1].split(";")[0]
        assert new_access and new_access != old_access
        claims = jwt.decode(new_access, jwt_secret, algorithms=["HS256"])
        assert claims["type"] == "access"
        assert claims["sub"] == admin_id
        assert claims["exp"] > int(_now().timestamp())

        # 3) retried original request now succeeds (send only the fresh access cookie)
        s2 = requests.Session()
        s2.cookies.set("access_token", new_access)
        me = s2.get(f"{api}/auth/me", timeout=30)
        assert me.status_code == 200
        assert me.json()["email"] == test_credentials["email"]

    def test_refresh_without_cookie_401(self, api):
        r = requests.post(f"{api}/auth/refresh", timeout=30)
        assert r.status_code == 401

    def test_refresh_with_expired_refresh_token_401(self, api, admin_id, jwt_secret):
        s = requests.Session()
        s.cookies.set("refresh_token", _forge(
            jwt_secret, sub=admin_id, type="refresh",
            exp=int((_now() - datetime.timedelta(days=1)).timestamp())))
        assert s.post(f"{api}/auth/refresh", timeout=30).status_code == 401

    def test_refresh_rejects_access_token_as_refresh(self, api, admin_id, jwt_secret):
        s = requests.Session()
        s.cookies.set("refresh_token", _forge(
            jwt_secret, sub=admin_id, email="x@y.z", type="access",
            exp=int((_now() + datetime.timedelta(minutes=30)).timestamp())))
        assert s.post(f"{api}/auth/refresh", timeout=30).status_code == 401

    def test_refresh_rejects_bad_signature(self, api, admin_id):
        s = requests.Session()
        s.cookies.set("refresh_token", _forge(
            "wrong-secret-0000000000000000", sub=admin_id, type="refresh",
            exp=int((_now() + datetime.timedelta(days=1)).timestamp())))
        assert s.post(f"{api}/auth/refresh", timeout=30).status_code == 401

    def test_refresh_rejects_stale_token_version(self, api, admin_id, jwt_secret):
        s = requests.Session()
        s.cookies.set("refresh_token", _forge(
            jwt_secret, sub=admin_id, ver=999, type="refresh",
            exp=int((_now() + datetime.timedelta(days=1)).timestamp())))
        assert s.post(f"{api}/auth/refresh", timeout=30).status_code == 401

    def test_login_sets_httponly_secure_cookies(self, api, test_credentials):
        s = requests.Session()
        r = s.post(f"{api}/auth/login", json={"email": test_credentials["email"],
                                             "password": test_credentials["password"]},
                   timeout=30)
        assert r.status_code == 200
        raw = "; ".join(r.headers.get_all("Set-Cookie") or []) \
            if hasattr(r.headers, "get_all") else r.headers.get("Set-Cookie", "")
        assert "access_token" in raw and "refresh_token" in raw
        assert raw.lower().count("httponly") >= 2
        assert raw.lower().count("secure") >= 2

    def test_logout_clears_cookies_and_me_401(self, api, test_credentials):
        s = requests.Session()
        s.post(f"{api}/auth/login", json={"email": test_credentials["email"],
                                          "password": test_credentials["password"]},
               timeout=30)
        assert s.get(f"{api}/auth/me", timeout=30).status_code == 200
        assert s.post(f"{api}/auth/logout", timeout=30).status_code in (200, 204)
        assert not s.cookies.get("access_token")
        assert s.get(f"{api}/auth/me", timeout=30).status_code == 401
