import asyncio
import importlib.util
from pathlib import Path
import sys

import httpx
import pytest


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


@pytest.mark.parametrize("purpose", ["first_access", "recovery"])
@pytest.mark.parametrize("origin", ["http://dacot-whatsapp:3002", "http://dacot-whatsapp:3002/"])
def test_explicit_private_transport_keeps_authentication_and_https_links(origin, purpose):
    import hashlib
    import hmac
    import json
    client, options = FakeClient(), {}
    def factory(**kwargs):
        options.update(kwargs)
        return client
    provider = module.WhatsAppDeliveryProvider(
        service_url=origin, service_transport="speedtrail-private-http", service_key="x" * 32,
        frontend_url="https://hub.example.test", client_factory=factory)
    assert asyncio.run(provider.send(number="11912345678", token="synthetic-token", purpose=purpose,
                                    request_id="private-request")) == module.DeliveryResult.ACCEPTED
    url, headers, body = client.calls[0]
    assert url == "http://dacot-whatsapp:3002/internal/auth-messages"
    assert headers["Authorization"] == "Bearer " + "x" * 32
    assert headers["Idempotency-Key"] == "private-request"
    raw = json.dumps(body, separators=(",", ":"), ensure_ascii=True).encode()
    assert headers["X-DACOT-Signature"] == hmac.new(
        b"x" * 32, headers["X-DACOT-Timestamp"].encode() + b"." + raw, hashlib.sha256).hexdigest()
    assert body["link"].startswith("https://hub.example.test/reset-password?token=")
    assert options == {"timeout": 10.0, "follow_redirects": False, "trust_env": False}


@pytest.mark.parametrize("origin", [
    "http://dacot-whatsapp", "http://dacot-whatsapp:80", "http://dacot-whatsapp:3003",
    "http://dacot-whatsapp:03002", "http://dacot-whatsapp:3002//",
    "http://dacot-whatsapp:3002/internal/auth-messages", "http://dacot-whatsapp:3002?x=1",
    "http://dacot-whatsapp:3002#fragment", "http://user:pass@dacot-whatsapp:3002",
    "http://dacot-whatsapp.evil.example:3002", "http://dacot-whatsapp.:3002",
    "http://DACOT-WHATSAPP:3002", "http://dacot-principal:8000",
    "http://dacot-whatsapp.speedtrail.com.br:3002", "http://public.example.test:3002",
    "http://127.0.0.1:3002", "http://169.254.169.254:3002", "http://[::1]:3002",
    "http://dacot-whatsapp:3002\n", "http://dacot-whatsapp:3002\\@evil.example",
])
def test_private_transport_rejects_every_other_http_destination_without_request(origin):
    client = FakeClient()
    provider = module.WhatsAppDeliveryProvider(service_url=origin, service_transport="speedtrail-private-http",
        service_key="x" * 32, frontend_url="https://hub.example.test", client_factory=lambda **_: client)
    assert asyncio.run(provider.send(number="11912345678", token="synthetic-token", purpose="recovery",
                                    request_id="r")) == module.DeliveryResult.UNAVAILABLE
    assert client.calls == []


@pytest.mark.parametrize("mode", ["https", "", "http", "private-http", "SPEEDTRAIL-PRIVATE-HTTP"])
def test_private_http_requires_exact_explicit_configuration(mode):
    client = FakeClient()
    provider = module.WhatsAppDeliveryProvider(service_url="http://dacot-whatsapp:3002", service_transport=mode,
        service_key="x" * 32, frontend_url="https://hub.example.test", client_factory=lambda **_: client)
    assert asyncio.run(provider.send(number="11912345678", token="synthetic-token", purpose="recovery",
                                    request_id="r")) == module.DeliveryResult.UNAVAILABLE
    assert client.calls == []


@pytest.mark.parametrize("mode", ["https", "speedtrail-private-http"])
def test_public_https_stays_valid_in_both_supported_modes(mode):
    client = FakeClient()
    provider = module.WhatsAppDeliveryProvider(service_url="https://sender.example.test", service_transport=mode,
        service_key="x" * 32, frontend_url="https://hub.example.test", client_factory=lambda **_: client)
    assert asyncio.run(provider.send(number="11912345678", token="synthetic-token", purpose="recovery",
                                    request_id="r")) == module.DeliveryResult.ACCEPTED


def test_actual_httpx_private_client_never_follows_redirect_or_environment_proxy(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.example.test:8080")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example.test:8080")
    calls = []
    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={"Location": "http://evil.example.test/collect"})
    def factory(**options):
        assert options["trust_env"] is False
        assert options["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **options)
    provider = module.WhatsAppDeliveryProvider(service_url="http://dacot-whatsapp:3002",
        service_transport="speedtrail-private-http", service_key="x" * 32,
        frontend_url="https://hub.example.test", client_factory=factory)
    assert asyncio.run(provider.send(number="11912345678", token="synthetic-token", purpose="recovery",
                                    request_id="r")) == module.DeliveryResult.UNAVAILABLE
    assert calls == ["http://dacot-whatsapp:3002/internal/auth-messages"]


def test_private_transport_never_allows_http_frontend_links():
    client = FakeClient()
    provider = module.WhatsAppDeliveryProvider(service_url="http://dacot-whatsapp:3002",
        service_transport="speedtrail-private-http", service_key="x" * 32,
        frontend_url="http://dacot-frontend:3000", client_factory=lambda **_: client)
    assert asyncio.run(provider.send(number="11912345678", token="synthetic-token", purpose="recovery",
                                    request_id="r")) == module.DeliveryResult.UNAVAILABLE
    assert client.calls == []


def test_pairing_code_delegation_uses_a_distinct_signed_secret_without_logging_it(caplog):
    import hashlib
    import hmac
    import json

    class PairingClient:
        def __init__(self): self.calls = []
        async def __aenter__(self): return self
        async def __aexit__(self, *_): return False
        async def post(self, url, *, headers, content):
            self.calls.append((url, headers, json.loads(content)))
            return httpx.Response(202, json={"code": "ABCD1234"})

    client, options = PairingClient(), {}
    def factory(**kwargs):
        options.update(kwargs)
        return client
    provider = module.WhatsAppPairingProvider(service_url="http://dacot-whatsapp:3002",
        service_transport="speedtrail-private-http", service_key="p" * 32, client_factory=factory)
    result = asyncio.run(provider.request_code(number="11912345678", request_id="pairing-request"))
    assert result.code == "ABCD1234"
    url, headers, body = client.calls[0]
    assert url == "http://dacot-whatsapp:3002/internal/pairing/code"
    assert body == {"destination": "5511912345678"}
    raw = json.dumps(body, separators=(",", ":"), ensure_ascii=True).encode()
    assert headers["X-DACOT-Signature"] == hmac.new(
        b"p" * 32, headers["X-DACOT-Timestamp"].encode() + b"." + raw, hashlib.sha256).hexdigest()
    assert options == {"timeout": 10.0, "follow_redirects": False, "trust_env": False}
    assert not caplog.text


def test_pairing_code_fails_closed_for_bad_origin_or_bad_gateway_response():
    provider = module.WhatsAppPairingProvider(service_url="http://gateway.example.test:3002",
        service_transport="speedtrail-private-http", service_key="p" * 32)
    assert asyncio.run(provider.request_code(number="11912345678", request_id="r")).code is None


def test_integration_status_uses_signed_private_request_and_exposes_only_safe_fields():
    import hashlib
    import hmac

    class StatusClient:
        def __init__(self): self.calls = []
        async def __aenter__(self): return self
        async def __aexit__(self, *_): return False
        async def get(self, url, *, headers):
            self.calls.append((url, headers))
            return httpx.Response(200, json={"connection_state": "open", "pairing_self_service_enabled": False})

    client, options = StatusClient(), {}
    def factory(**kwargs):
        options.update(kwargs)
        return client
    provider = module.WhatsAppStatusProvider(
        service_url="http://dacot-whatsapp:3002", service_transport="speedtrail-private-http",
        service_key="s" * 32, client_factory=factory,
    )
    result = asyncio.run(provider.get_status(request_id="status-request-unique-123"))
    assert result.gateway_reachable is True
    assert result.connection_state == "open"
    assert result.pairing_self_service_enabled is False
    url, headers = client.calls[0]
    assert url == "http://dacot-whatsapp:3002/internal/integration-status"
    signed = f"GET\\n/internal/integration-status\\n{headers['X-DACOT-Timestamp']}\\n{headers['Idempotency-Key']}".encode()
    assert headers["X-DACOT-Signature"] == hmac.new(b"s" * 32, signed, hashlib.sha256).hexdigest()
    assert options == {"timeout": 3.0, "follow_redirects": False, "trust_env": False}


@pytest.mark.parametrize("status, payload", [
    (503, {}),
    (200, {"connection_state": "unknown", "pairing_self_service_enabled": False}),
    (200, {"connection_state": "open", "pairing_self_service_enabled": "true"}),
    (200, []),
])
def test_integration_status_timeout_or_invalid_response_is_unavailable(status, payload):
    class StatusClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *_): return False
        async def get(self, *_args, **_kwargs): return httpx.Response(status, json=payload)

    provider = module.WhatsAppStatusProvider(service_url="https://sender.example.test", service_key="s" * 32,
                                               client_factory=lambda **_: StatusClient())
    result = asyncio.run(provider.get_status(request_id="status-request-unique-123"))
    assert result.gateway_reachable is False
    assert result.connection_state == "unavailable"
    assert result.pairing_self_service_enabled is False


def test_integration_status_rejects_untrusted_http_destination_without_request():
    called = False
    def factory(**_):
        nonlocal called
        called = True
        raise AssertionError("client should not be created")
    provider = module.WhatsAppStatusProvider(service_url="http://gateway.example.test:3002",
        service_transport="speedtrail-private-http", service_key="s" * 32, client_factory=factory)
    result = asyncio.run(provider.get_status(request_id="status-request-unique-123"))
    assert result.gateway_reachable is False
    assert called is False


def test_integration_status_timeout_is_unavailable_without_logging_credentials(caplog):
    class TimeoutClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *_): return False
        async def get(self, *_args, **_kwargs):
            raise httpx.ReadTimeout("synthetic status timeout")

    provider = module.WhatsAppStatusProvider(service_url="https://sender.example.test", service_key="s" * 32,
                                               client_factory=lambda **_: TimeoutClient())
    result = asyncio.run(provider.get_status(request_id="status-request-unique-123"))
    assert result.gateway_reachable is False
    assert result.connection_state == "unavailable"
    assert "s" * 32 not in caplog.text
