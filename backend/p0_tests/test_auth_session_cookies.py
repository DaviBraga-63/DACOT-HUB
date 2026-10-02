"""P0 coverage for browser-session authentication cookies."""

import requests


def _auth_cookies(response):
    return [
        cookie for cookie in response.raw.headers.getlist("Set-Cookie")
        if cookie.startswith(("access_token=", "refresh_token="))
    ]


def _cookie_header(response):
    cookies = response.cookies
    return f"access_token={cookies['access_token']}; refresh_token={cookies['refresh_token']}"


def test_auth_cookies_are_secure_browser_session_cookies(services):
    service = services
    login = requests.post(
        service.hub + "/api/auth/login",
        json={"email": service.admin_email, "password": service.password},
        timeout=10,
    )
    assert login.status_code == 200, login.text

    cookies = _auth_cookies(login)
    assert len(cookies) == 2
    for cookie in cookies:
        assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=none" in cookie, cookie
        assert "Max-Age" not in cookie and "expires=" not in cookie.lower(), cookie

    headers = {"Cookie": _cookie_header(login)}
    assert requests.get(service.hub + "/api/auth/me", headers=headers, timeout=10).status_code == 200

    refresh = requests.post(service.hub + "/api/auth/refresh", headers=headers, timeout=10)
    assert refresh.status_code == 200, refresh.text
    refreshed_access = _auth_cookies(refresh)
    assert len(refreshed_access) == 1
    assert "access_token=" in refreshed_access[0]
    assert "HttpOnly" in refreshed_access[0] and "Secure" in refreshed_access[0]
    assert "SameSite=none" in refreshed_access[0]
    assert "Max-Age" not in refreshed_access[0] and "expires=" not in refreshed_access[0].lower()

    logout = requests.post(service.hub + "/api/auth/logout", headers=headers, timeout=10)
    assert logout.status_code == 200, logout.text
    deleted = _auth_cookies(logout)
    assert len(deleted) == 2
    for cookie in deleted:
        assert "Max-Age=0" in cookie and "HttpOnly" in cookie and "Secure" in cookie, cookie
        assert "SameSite=none" in cookie, cookie

    assert requests.get(service.hub + "/api/auth/me", timeout=10).status_code == 401
    assert requests.post(service.hub + "/api/auth/refresh", timeout=10).status_code == 401
