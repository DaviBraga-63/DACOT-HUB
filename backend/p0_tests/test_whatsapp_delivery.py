import asyncio
import importlib.util
from pathlib import Path
import sys

import httpx


backend = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("whatsapp_numbers", backend / "whatsapp_numbers.py")
numbers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(numbers)
sys.modules.setdefault("whatsapp_numbers", numbers)
spec = importlib.util.spec_from_file_location("whatsapp_delivery_test", backend / "whatsapp_delivery.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FakeClient:
    def __init__(self, *, status=202, error=None):
        self.status, self.error, self.calls = status, error, []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def post(self, url, *, headers, content):
        import json
        self.calls.append((url, headers, json.loads(content)))
        if self.error:
            raise self.error
        return httpx.Response(self.status)


def test_accepted_request_is_not_a_delivery_receipt():
    client = FakeClient()
    provider = module.WhatsAppDeliveryProvider(service_url="https://sender.example.test", service_key="x" * 32,
                                                frontend_url="https://hub.example.test", client_factory=lambda **_: client)
    result = asyncio.run(provider.send(number="(11) 91234-5678", token="synthetic-token", purpose="recovery", request_id="request-1"))
    assert result == module.DeliveryResult.ACCEPTED
    assert client.calls[0][2]["destination"] == "+5511912345678"
    assert client.calls[0][2]["link"] == "https://hub.example.test/reset-password?token=synthetic-token"
    assert client.calls[0][1]["Idempotency-Key"] == "request-1"


def test_failure_or_insecure_configuration_fails_closed(caplog):
    client = FakeClient(error=httpx.ConnectTimeout("synthetic"))
    for service_url, key in (("http://sender.example.test", "x" * 32), ("https://sender.example.test", "short"),
                             ("https://sender.example.test", "x" * 32)):
        provider = module.WhatsAppDeliveryProvider(service_url=service_url, service_key=key,
                                                    frontend_url="https://hub.example.test", client_factory=lambda **_: client)
        assert asyncio.run(provider.send(number="11912345678", token="synthetic-token", purpose="recovery", request_id="r")) == module.DeliveryResult.UNAVAILABLE
    assert "synthetic-token" not in caplog.text
    assert "x" * 32 not in caplog.text


def test_sender_rejection_and_redirect_are_not_success():
    for status in (302, 400, 429, 500, 503):
        client = FakeClient(status=status)
        provider = module.WhatsAppDeliveryProvider(service_url="https://sender.example.test", service_key="x" * 32,
                                                    frontend_url="https://hub.example.test", client_factory=lambda **_: client)
        result = asyncio.run(provider.send(number="11912345678", token="synthetic-token", purpose="recovery", request_id="r"))
        assert result == module.DeliveryResult.UNAVAILABLE


def test_missing_tls_ca_does_not_break_completed_onboarding():
    def missing_ca(**_):
        raise FileNotFoundError("synthetic missing CA")
    provider = module.WhatsAppDeliveryProvider(service_url="https://sender.example.test", service_key="x" * 32,
                                                frontend_url="https://hub.example.test", client_factory=missing_ca,
                                                ca_file="missing-test-ca.pem")
    result = asyncio.run(provider.send(number="11912345678", token="synthetic-token", purpose="first_access", request_id="r"))
    assert result == module.DeliveryResult.UNAVAILABLE


def test_public_https_uses_default_certificate_validation_and_signed_body():
    import hashlib
    import hmac
    import json
    options = {}
    client = FakeClient()
    def factory(**kwargs):
        options.update(kwargs)
        return client
    provider = module.WhatsAppDeliveryProvider(
        service_url="https://sender.example.test", service_key="x" * 32,
        frontend_url="https://hub.example.test", client_factory=factory)
    assert asyncio.run(provider.send(number="11912345678", token="synthetic-token",
                                    purpose="recovery", request_id="r")) == module.DeliveryResult.ACCEPTED
    assert "verify" not in options  # httpx default verifies CA and hostname.
    assert options["follow_redirects"] is False
    assert options["timeout"] == 10.0
    _, headers, body = client.calls[0]
    raw = json.dumps(body, separators=(",", ":"), ensure_ascii=True).encode()
    signed = hmac.new(b"x" * 32, headers["X-DACOT-Timestamp"].encode() + b"." + raw, hashlib.sha256).hexdigest()
    assert headers["X-DACOT-Signature"] == signed


def test_tls_failure_is_unavailable_without_leaking_credentials(caplog):
    client = FakeClient(error=httpx.ConnectError("synthetic certificate verification failure"))
    provider = module.WhatsAppDeliveryProvider(service_url="https://sender.example.test", service_key="x" * 32,
        frontend_url="https://hub.example.test", client_factory=lambda **_: client)
    assert asyncio.run(provider.send(number="11912345678", token="synthetic-token",
                                    purpose="recovery", request_id="r")) == module.DeliveryResult.UNAVAILABLE
    assert not caplog.text
