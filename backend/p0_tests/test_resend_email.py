"""Unit coverage for the isolated Resend password-reset delivery adapter."""

import asyncio
import importlib.util
from pathlib import Path

import httpx


BACKEND = Path(__file__).resolve().parents[1]


def load_email_delivery():
    spec = importlib.util.spec_from_file_location("email_delivery_test", BACKEND / "email_delivery.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


email_delivery = load_email_delivery()


class _Client:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def post(self, url, *, headers, json):
        self.calls.append({"url": url, "headers": headers, "json": json})
        if self.error:
            raise self.error
        return self.response


def _send(**overrides):
    values = {
        "to_email": "manager@example.test",
        "token": "synthetic-one-time-token",
        "frontend_url": "https://hub.example.test",
        "resend_api_key": "synthetic-api-key",
        "email_from_address": "onboarding@resend.dev",
        "email_from_name": "DACOT",
    }
    values.update(overrides)
    return asyncio.run(email_delivery.send_password_reset_email(**values))


def _install_client(monkeypatch, client):
    monkeypatch.setattr(email_delivery.httpx, "AsyncClient", lambda **_kwargs: client)


def test_resend_rejects_missing_configuration_without_logging_token(caplog):
    assert _send(resend_api_key="") is False
    assert _send(email_from_address="") is False
    assert "synthetic-one-time-token" not in caplog.text
    assert "synthetic-api-key" not in caplog.text


def test_resend_request_uses_official_endpoint_and_safe_payload(monkeypatch):
    request = httpx.Request("POST", email_delivery.RESEND_EMAILS_URL)
    client = _Client(response=httpx.Response(202, request=request))
    _install_client(monkeypatch, client)

    assert _send() is True
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["url"] == "https://api.resend.com/emails"
    assert call["headers"]["Authorization"] == "Bearer synthetic-api-key"
    assert call["headers"]["Content-Type"] == "application/json"
    assert call["json"]["from"] == "DACOT <onboarding@resend.dev>"
    assert call["json"]["to"] == ["manager@example.test"]
    assert "https://hub.example.test/reset-password?token=synthetic-one-time-token" in call["json"]["html"]


def test_resend_http_and_network_failures_return_false_without_logging_secrets(monkeypatch, caplog):
    for status in (400, 500):
        request = httpx.Request("POST", email_delivery.RESEND_EMAILS_URL)
        client = _Client(response=httpx.Response(status, request=request))
        _install_client(monkeypatch, client)
        assert _send() is False

    _install_client(monkeypatch, _Client(error=httpx.ConnectTimeout("synthetic timeout")))
    assert _send() is False
    assert "synthetic-one-time-token" not in caplog.text
    assert "synthetic-api-key" not in caplog.text
