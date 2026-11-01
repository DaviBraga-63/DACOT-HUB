"""Isolated adapter for the WhatsApp sender; never logs credentials or links.

Acceptance by the sender is not proof that WhatsApp delivered the message.
Authorization of the destination must happen in the Hub before this adapter is
called. This module does not expose an endpoint to browsers.
"""

from enum import Enum
import hashlib
import hmac
import json
import re
import time
from urllib.parse import quote, urlsplit

import httpx

from whatsapp_numbers import normalize_brazilian_number


class DeliveryResult(str, Enum):
    ACCEPTED = "accepted"
    UNAVAILABLE = "unavailable"


class PairingCodeResult:
    """A one-time WhatsApp linking code, intentionally never persisted here."""

    def __init__(self, code: str | None = None):
        self.code = code


class IntegrationStatusResult:
    """Sanitized operational state returned by the WhatsApp gateway only."""

    def __init__(self, *, connection_state: str = "unavailable", gateway_reachable: bool = False,
                 pairing_self_service_enabled: bool = False, connected_account_phone: str | None = None):
        self.connection_state = connection_state
        self.gateway_reachable = gateway_reachable
        self.pairing_self_service_enabled = pairing_self_service_enabled
        self.connected_account_phone = connected_account_phone


def _https_origin(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        return (parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username
                and not parsed.password and not parsed.query and not parsed.fragment
                and parsed.path in ("", "/") and (parsed.port is None or 1 <= parsed.port <= 65535))
    except ValueError:
        return False


def _service_origin(value: str, transport: str) -> bool:
    """Only the explicitly selected SpeedTrail service may use plaintext HTTP.

    Compare the complete configured origin, not a suffix, IP range or forwarded
    header. No user-controlled destination can opt into this transport.
    """
    if transport not in {"https", "speedtrail-private-http"}:
        return False
    if _https_origin(value):
        return True
    return transport == "speedtrail-private-http" and value in {
        "http://dacot-whatsapp:3002", "http://dacot-whatsapp:3002/",
    }


class WhatsAppDeliveryProvider:
    def __init__(self, *, service_url: str, service_key: str, frontend_url: str, client_factory=None,
                 ca_file=None, service_transport: str = "https"):
        self.configured_service_url = service_url
        self.service_url = service_url.rstrip("/")
        self.service_transport = service_transport
        self.service_key = service_key
        self.frontend_url = frontend_url.rstrip("/")
        self.client_factory = client_factory or httpx.AsyncClient
        self.ca_file = ca_file

    async def send(self, *, number: str, token: str, purpose: str, request_id: str) -> DeliveryResult:
        if (not _service_origin(self.configured_service_url, self.service_transport) or not _https_origin(self.frontend_url)
                or len(self.service_key) < 32 or purpose not in {"first_access", "recovery"}
                or not request_id or len(request_id) > 128 or not token):
            return DeliveryResult.UNAVAILABLE
        try:
            destination = normalize_brazilian_number(number)
            link = f"{self.frontend_url}/reset-password?token={quote(token, safe='')}"
            # Never leak internal credentials/body through HTTP(S)_PROXY or
            # proxy auto-configuration inherited from the execution environment.
            options = {"timeout": 10.0, "follow_redirects": False, "trust_env": False}
            if self.ca_file:
                options["verify"] = self.ca_file
            async with self.client_factory(**options) as client:
                body = json.dumps({"destination": destination, "purpose": purpose, "link": link},
                                  separators=(",", ":"), ensure_ascii=True).encode("utf-8")
                timestamp = str(int(time.time()))
                signature = hmac.new(self.service_key.encode(), timestamp.encode() + b"." + body,
                                     hashlib.sha256).hexdigest()
                response = await client.post(
                    f"{self.service_url}/internal/auth-messages",
                    headers={"Authorization": f"Bearer {self.service_key}", "Idempotency-Key": request_id,
                             "X-DACOT-Timestamp": timestamp, "X-DACOT-Signature": signature,
                             "Content-Type": "application/json"}, content=body,
                )
            return DeliveryResult.ACCEPTED if response.status_code in (200, 202) else DeliveryResult.UNAVAILABLE
        except (httpx.HTTPError, ValueError, OSError):
            return DeliveryResult.UNAVAILABLE


class WhatsAppPairingProvider:
    """Narrow, separately-authenticated delegation for an emergency pairing code.

    This is deliberately distinct from both the delivery credential and the
    loopback-only administrative credential.  It cannot read QR/state or reset
    the session, and it never writes the returned code to disk or logs.
    """

    def __init__(self, *, service_url: str, service_key: str, client_factory=None,
                 ca_file=None, service_transport: str = "https"):
        self.configured_service_url = service_url
        self.service_url = service_url.rstrip("/")
        self.service_transport = service_transport
        self.service_key = service_key
        self.client_factory = client_factory or httpx.AsyncClient
        self.ca_file = ca_file

    async def request_code(self, *, number: str, request_id: str) -> PairingCodeResult:
        if (not _service_origin(self.configured_service_url, self.service_transport)
                or len(self.service_key) < 32 or not request_id or len(request_id) > 128):
            return PairingCodeResult()
        try:
            # Baileys accepts country code plus digits, without a plus sign.
            destination = normalize_brazilian_number(number).lstrip("+")
            body = json.dumps({"destination": destination}, separators=(",", ":"),
                              ensure_ascii=True).encode("utf-8")
            timestamp = str(int(time.time()))
            signature = hmac.new(self.service_key.encode(), timestamp.encode() + b"." + body,
                                 hashlib.sha256).hexdigest()
            options = {"timeout": 10.0, "follow_redirects": False, "trust_env": False}
            if self.ca_file:
                options["verify"] = self.ca_file
            async with self.client_factory(**options) as client:
                response = await client.post(
                    f"{self.service_url}/internal/pairing/code",
                    headers={"Authorization": f"Bearer {self.service_key}", "Idempotency-Key": request_id,
                             "X-DACOT-Timestamp": timestamp, "X-DACOT-Signature": signature,
                             "Content-Type": "application/json"}, content=body,
                )
            if response.status_code != 202:
                return PairingCodeResult()
            code = response.json().get("code")
            return PairingCodeResult(code if isinstance(code, str) and re.fullmatch(r"[A-Z0-9]{4}-?[A-Z0-9]{4}", code) else None)
        except (httpx.HTTPError, ValueError, OSError, json.JSONDecodeError):
            return PairingCodeResult()


class WhatsAppStatusProvider:
    """Read the narrow, non-sensitive gateway status through the private service path."""

    _KNOWN_CONNECTION_STATES = {
        "open", "connecting", "pairing", "disconnected", "logged_out", "error", "stopped", "disabled",
    }

    def __init__(self, *, service_url: str, service_key: str, client_factory=None,
                 ca_file=None, service_transport: str = "https"):
        self.configured_service_url = service_url
        self.service_url = service_url.rstrip("/")
        self.service_transport = service_transport
        self.service_key = service_key
        self.client_factory = client_factory or httpx.AsyncClient
        self.ca_file = ca_file

    async def get_status(self, *, request_id: str) -> IntegrationStatusResult:
        if (not _service_origin(self.configured_service_url, self.service_transport)
                or len(self.service_key) < 32 or not request_id or len(request_id) > 128):
            return IntegrationStatusResult()
        try:
            timestamp = str(int(time.time()))
            signed = f"GET\n/internal/integration-status\n{timestamp}\n{request_id}".encode()
            signature = hmac.new(self.service_key.encode(), signed, hashlib.sha256).hexdigest()
            options = {"timeout": 3.0, "follow_redirects": False, "trust_env": False}
            if self.ca_file:
                options["verify"] = self.ca_file
            async with self.client_factory(**options) as client:
                response = await client.get(
                    f"{self.service_url}/internal/integration-status",
                    headers={"Authorization": f"Bearer {self.service_key}", "Idempotency-Key": request_id,
                             "X-DACOT-Timestamp": timestamp, "X-DACOT-Signature": signature},
                )
            if response.status_code != 200:
                return IntegrationStatusResult()
            data = response.json()
            if not isinstance(data, dict):
                return IntegrationStatusResult()
            state = data.get("connection_state")
            pairing_enabled = data.get("pairing_self_service_enabled")
            if state not in self._KNOWN_CONNECTION_STATES or not isinstance(pairing_enabled, bool):
                return IntegrationStatusResult()
            phone = data.get("connected_account_phone")
            if phone is not None:
                try:
                    phone = normalize_brazilian_number(phone)
                except ValueError:
                    phone = None
            return IntegrationStatusResult(
                connection_state=state,
                gateway_reachable=True,
                pairing_self_service_enabled=pairing_enabled,
                connected_account_phone=phone,
            )
        except (httpx.HTTPError, ValueError, OSError, json.JSONDecodeError):
            return IntegrationStatusResult()
