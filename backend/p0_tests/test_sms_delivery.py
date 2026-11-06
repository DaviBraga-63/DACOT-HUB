import asyncio
import importlib.util
from pathlib import Path
import sys

import httpx
import pytest


backend = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(backend))
spec = importlib.util.spec_from_file_location("phone_numbers_test", backend / "phone_numbers.py")
phones = importlib.util.module_from_spec(spec)
spec.loader.exec_module(phones)
sys.modules.setdefault("phone_numbers", phones)
spec = importlib.util.spec_from_file_location("sms_delivery_test", backend / "sms_delivery.py")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class FakeClient:
    def __init__(self, *, status=201, payload=None, error=None):
        self.status, self.payload, self.error, self.calls = status, payload or {}, error, []

    async def __aenter__(self): return self
    async def __aexit__(self, *_): return False

    async def post(self, url, *, data, auth):
        self.calls.append((url, data, auth))
        if self.error:
            raise self.error
        return httpx.Response(self.status, json=self.payload)


def provider(client):
    return module.SmsDeliveryProvider(
        provider="twilio", account_sid="AC" + "a" * 32, auth_token="synthetic-secret",
        sender="+15551234567", client_factory=lambda **options: client,
    )


def test_accepted_sms_uses_https_basic_auth_and_e164():
    client = FakeClient(payload={"sid": "SM" + "b" * 32, "status": "queued"})
    result = asyncio.run(provider(client).send(number="(11) 91234-5678", message="synthetic message"))
    assert result.state == "accepted"
    assert result.http_status == 201
    assert result.provider_message_id == "SM" + "b" * 32
    url, data, auth = client.calls[0]
    assert url.startswith("https://api.twilio.com/")
    assert data["To"] == "+5511912345678"
    assert auth == ("AC" + "a" * 32, "synthetic-secret")


def test_invalid_config_or_phone_fails_closed_without_request():
    client = FakeClient()
    invalid_config = module.SmsDeliveryProvider(provider="unknown", account_sid="", auth_token="",
        sender="", client_factory=lambda **_: client)
    assert asyncio.run(invalid_config.send(number="11912345678", message="x")).state == "configuration_error"
    assert asyncio.run(provider(client).send(number="bad", message="x")).state == "failed"
    assert asyncio.run(provider(client).send(number="(21) 3456-7890", message="x")).state == "failed"
    assert client.calls == []


@pytest.mark.parametrize("status,payload,expected", [
    (201, {"sid": "SM" + "b" * 32, "status": "queued"}, "accepted"),
    (201, {"sid": "SM" + "b" * 32, "status": "sent"}, "sent"),
    (201, {"sid": "SM" + "b" * 32, "status": "delivered"}, "delivered"),
    (201, {"sid": "SM" + "b" * 32, "status": "undelivered"}, "undelivered"),
    (400, {"code": 21211}, "failed"),
    (401, {"code": 20003}, "failed"),
    (500, {}, "failed"),
    (201, {"sid": "invalid", "status": "queued"}, "failed"),
])
def test_provider_rejections_are_not_reported_as_accepted(status, payload, expected):
    client = FakeClient(status=status, payload=payload)
    result = asyncio.run(provider(client).send(number="11912345678", message="synthetic message"))
    assert result.state == expected
    assert result.provider_message_id is None


@pytest.mark.parametrize("error", [httpx.TimeoutException("timeout"), httpx.ConnectError("offline")])
def test_timeout_and_network_errors_are_unknown(error):
    client = FakeClient(error=error)
    result = asyncio.run(provider(client).send(number="11912345678", message="synthetic message"))
    assert result.state == "unknown"
