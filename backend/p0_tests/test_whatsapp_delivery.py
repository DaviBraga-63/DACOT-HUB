import asyncio
import hashlib
import hmac
import json
from types import SimpleNamespace

import httpx
import pytest

from backend.whatsapp_delivery import (
    DeliveryResult, WhatsAppAccountSwitchProvider, WhatsAppDeliveryProvider,
    WhatsAppPairingProvider, WhatsAppStatusProvider,
)


class FakeClient:
    def __init__(self, *, response=None, error=None, **options):
        self.response = response or httpx.Response(202, json={"state": "accepted"})
        self.error = error
        self.options = options
        self.calls = []

    async def __aenter__(self): return self
    async def __aexit__(self, *_): return False

    async def post(self, url, *, headers, content):
        self.calls.append(("POST", url, headers, content))
        if self.error:
            raise self.error
        return self.response

    async def get(self, url, *, headers):
        self.calls.append(("GET", url, headers, b""))
        if self.error:
            raise self.error
        return self.response

    async def request(self, method, url, *, content, headers):
        self.calls.append((method, url, headers, content))
        if self.error:
            raise self.error
        return self.response


def fake_factory(client):
    return lambda **options: (setattr(client, "options", options) or client)


def delivery(client, **overrides):
    return WhatsAppDeliveryProvider(
        service_url="https://whatsapp.example.test", service_key="k" * 40,
        frontend_url="https://hub.example.test", client_factory=fake_factory(client), **overrides,
    )


def test_delivery_uses_hmac_timestamp_idempotency_and_neutral_phone():
    client = FakeClient()
    token = "A" * 43
    result = asyncio.run(delivery(client).send(
        number="(11) 91234-5678", token=token, purpose="first_access", request_id=hashlib.sha256(token.encode()).hexdigest()))
    assert result is DeliveryResult.ACCEPTED
    method, url, headers, raw = client.calls[0]
    body = json.loads(raw)
    assert method == "POST" and url.endswith("/internal/auth-messages")
    assert body["destination"] == "+5511912345678"
    assert body["link"] == f"https://hub.example.test/reset-password?token={token}"
    assert headers["Authorization"] == f"Bearer {'k' * 40}"
    assert headers["Idempotency-Key"] == hashlib.sha256(token.encode()).hexdigest()
    assert hmac.compare_digest(headers["X-DACOT-Signature"],
        hmac.new(b"k" * 40, headers["X-DACOT-Timestamp"].encode() + b"." + raw, hashlib.sha256).hexdigest())
    assert client.options["timeout"] == 10.0
    assert client.options["trust_env"] is False


@pytest.mark.parametrize("status,payload,expected", [
    (202, {"state": "accepted"}, "accepted"),
    (401, {}, "rejected"),
    (429, {}, "rate_limited"),
    (409, {"state": "indeterminate"}, "indeterminate"),
    (503, {"state": "indeterminate"}, "indeterminate"),
    (503, {}, "failed"),
])
def test_delivery_states_do_not_claim_delivery(status, payload, expected):
    client = FakeClient(response=httpx.Response(status, json=payload))
    token = "B" * 43
    result = asyncio.run(delivery(client).send(number="11912345678", token=token,
        purpose="recovery", request_id=hashlib.sha256(token.encode()).hexdigest()))
    assert result.value == expected
    assert result.value != "delivered"


def test_delivery_classifies_invalid_config_phone_and_network_error():
    token = "C" * 43
    client = FakeClient(error=httpx.TimeoutException("synthetic timeout"))
    valid = delivery(client)
    assert asyncio.run(valid.send(number="11912345678", token=token, purpose="recovery", request_id="bad")) is DeliveryResult.CONFIGURATION_ERROR
    assert asyncio.run(valid.send(number="(21) 3456-7890", token=token, purpose="recovery",
                                  request_id=hashlib.sha256(token.encode()).hexdigest())) is DeliveryResult.REJECTED
    assert asyncio.run(valid.send(number="11912345678", token=token, purpose="recovery",
                                  request_id=hashlib.sha256(token.encode()).hexdigest())) is DeliveryResult.NETWORK_ERROR


def test_pairing_and_status_have_separate_signed_api_contracts():
    pairing_client = FakeClient(response=httpx.Response(202, json={"code": "ABCD1234"}))
    pairing = WhatsAppPairingProvider(service_url="https://whatsapp.example.test", service_key="p" * 40,
                                      client_factory=fake_factory(pairing_client))
    result = asyncio.run(pairing.request_code(number="11912345678", request_id="pair-request-identifier-1"))
    assert result.code == "ABCD1234"
    _, path, headers, raw = pairing_client.calls[0]
    assert path.endswith("/internal/pairing/code")
    assert json.loads(raw) == {"destination": "5511912345678"}
    assert headers["Authorization"] == f"Bearer {'p' * 40}"

    status_client = FakeClient(response=httpx.Response(200, json={
        "connection_state": "open", "pairing_self_service_enabled": True,
    }))
    status = WhatsAppStatusProvider(service_url="https://whatsapp.example.test", service_key="k" * 40,
                                    client_factory=fake_factory(status_client))
    state = asyncio.run(status.get_status(request_id="status-request-identifier-1"))
    assert state.gateway_reachable and state.connection_state == "open" and state.pairing_enabled


def test_account_switch_uses_a_separate_signed_control_contract():
    client = FakeClient(response=httpx.Response(202, json={"state": "ready", "expires_at": 12345}))
    provider = WhatsAppAccountSwitchProvider(
        service_url="http://dacot-whatsapp:3002", service_key="s" * 40,
        service_transport="speedtrail-private-http", client_factory=fake_factory(client),
    )
    operation_id = "a" * 48
    result = asyncio.run(provider.prepare(operation_id=operation_id, number="(11) 91234-5678",
                                          request_id="switch-request-identifier-1"))
    assert result.available and result.state == "ready" and result.expires_at == 12345
    method, url, headers, raw = client.calls[0]
    assert method == "POST" and url.endswith(f"/internal/account-switch/{operation_id}/prepare")
    assert json.loads(raw) == {"phone": "5511912345678"}
    digest = hashlib.sha256(raw).hexdigest()
    signed = f"{method}\n/internal/account-switch/{operation_id}/prepare\n{headers['X-DACOT-Timestamp']}\n{headers['Idempotency-Key']}\n{digest}".encode()
    assert headers["X-DACOT-Signature"] == hmac.new(b"s" * 40, signed, hashlib.sha256).hexdigest()
