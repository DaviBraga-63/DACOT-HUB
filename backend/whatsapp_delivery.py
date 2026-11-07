"""Narrow authenticated Hub adapter for the private WhatsApp sender service."""

from dataclasses import dataclass
from enum import Enum
import hashlib
import hmac
import json
import re
import time
from urllib.parse import quote, urlsplit

import httpx

from phone_numbers import normalize_brazilian_mobile, normalize_brazilian_phone


class DeliveryResult(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    NETWORK_ERROR = "network_error"
    CONFIGURATION_ERROR = "configuration_error"
    RATE_LIMITED = "rate_limited"
    INDETERMINATE = "indeterminate"
    FAILED = "failed"


@dataclass(frozen=True)
class PairingCodeResult:
    code: str | None = None


@dataclass(frozen=True)
class IntegrationStatusResult:
    connection_state: str = "unavailable"
    gateway_reachable: bool = False
    pairing_enabled: bool = False


def _https_origin(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        return (parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username
                and not parsed.password and not parsed.query and not parsed.fragment
                and parsed.path in ("", "/") and (parsed.port is None or 1 <= parsed.port <= 65535))
    except ValueError:
        return False


def _service_origin(value: str, transport: str) -> bool:
    if _https_origin(value):
        return True
    return transport == "speedtrail-private-http" and value.rstrip("/") == "http://dacot-whatsapp:3002"


class _WhatsAppServiceClient:
    def __init__(self, *, service_url: str, service_key: str, client_factory=None, ca_file=None,
                 service_transport: str = "https"):
        self.configured_service_url = service_url
        self.service_url = service_url.rstrip("/")
        self.service_key = service_key
        self.client_factory = client_factory or httpx.AsyncClient
        self.ca_file = ca_file
        self.service_transport = service_transport

    def _valid_config(self) -> bool:
        return (_service_origin(self.configured_service_url, self.service_transport)
                and len(self.service_key) >= 32)

    def _client_options(self, timeout: float = 10.0) -> dict:
        options = {"timeout": timeout, "follow_redirects": False, "trust_env": False}
        if self.ca_file:
            options["verify"] = self.ca_file
        return options

    async def _post_signed(self, path: str, *, key: str, request_id: str, body: dict):
        raw_body = json.dumps(body, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        timestamp = str(int(time.time()))
        signature = hmac.new(key.encode(), timestamp.encode() + b"." + raw_body, hashlib.sha256).hexdigest()
        async with self.client_factory(**self._client_options()) as client:
            return await client.post(
                f"{self.service_url}{path}",
                headers={"Authorization": f"Bearer {key}", "Idempotency-Key": request_id,
                         "X-DACOT-Timestamp": timestamp, "X-DACOT-Signature": signature,
                         "Content-Type": "application/json"},
                content=raw_body,
            )


class WhatsAppDeliveryProvider(_WhatsAppServiceClient):
    async def send(self, *, number: str, token: str, purpose: str, request_id: str) -> DeliveryResult:
        if (not self._valid_config() or not _https_origin(self.frontend_url)
                or purpose not in {"first_access", "recovery"}
                or not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", request_id or "")
                or not token):
            return DeliveryResult.CONFIGURATION_ERROR
        try:
            destination = normalize_brazilian_mobile(number)
        except ValueError:
            return DeliveryResult.REJECTED
        try:
            link = f"{self.frontend_url.rstrip('/')}/reset-password?token={quote(token, safe='')}"
            response = await self._post_signed("/internal/auth-messages", key=self.service_key,
                                               request_id=request_id,
                                               body={"destination": destination, "purpose": purpose, "link": link})
            try:
                data = response.json()
                state = data.get("state") if isinstance(data, dict) else None
            except (ValueError, json.JSONDecodeError):
                state = None
            if response.status_code in {200, 202} and state == "accepted":
                return DeliveryResult.ACCEPTED
            if state == "indeterminate" or response.status_code == 409:
                return DeliveryResult.INDETERMINATE
            if response.status_code == 429:
                return DeliveryResult.RATE_LIMITED
            if response.status_code in {400, 401, 403, 404}:
                return DeliveryResult.REJECTED
            return DeliveryResult.FAILED
        except (httpx.HTTPError, OSError):
            return DeliveryResult.NETWORK_ERROR

    def __init__(self, *, service_url: str, service_key: str, frontend_url: str, client_factory=None,
                 ca_file=None, service_transport: str = "https"):
        super().__init__(service_url=service_url, service_key=service_key, client_factory=client_factory,
                         ca_file=ca_file, service_transport=service_transport)
        self.frontend_url = frontend_url


class WhatsAppPairingProvider(_WhatsAppServiceClient):
    async def request_code(self, *, number: str, request_id: str) -> PairingCodeResult:
        if (not self._valid_config()
                or not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", request_id or "")):
            return PairingCodeResult()
        try:
            destination = normalize_brazilian_mobile(number).lstrip("+")
            response = await self._post_signed("/internal/pairing/code", key=self.service_key,
                                               request_id=request_id,
                                               body={"destination": destination})
            if response.status_code != 202:
                return PairingCodeResult()
            code = response.json().get("code")
            return PairingCodeResult(code if isinstance(code, str)
                                     and re.fullmatch(r"[A-Z0-9]{4}-?[A-Z0-9]{4}", code) else None)
        except (httpx.HTTPError, ValueError, OSError, json.JSONDecodeError):
            return PairingCodeResult()


class WhatsAppStatusProvider(_WhatsAppServiceClient):
    async def get_status(self, *, request_id: str) -> IntegrationStatusResult:
        if (not self._valid_config()
                or not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", request_id or "")):
            return IntegrationStatusResult()
        try:
            timestamp = str(int(time.time()))
            signed = f"GET\n/internal/integration-status\n{timestamp}\n{request_id}".encode()
            signature = hmac.new(self.service_key.encode(), signed, hashlib.sha256).hexdigest()
            async with self.client_factory(**self._client_options(timeout=3.0)) as client:
                response = await client.get(
                    f"{self.service_url}/internal/integration-status",
                    headers={"Authorization": f"Bearer {self.service_key}", "Idempotency-Key": request_id,
                             "X-DACOT-Timestamp": timestamp, "X-DACOT-Signature": signature},
                )
            data = response.json()
            if response.status_code != 200 or not isinstance(data, dict):
                return IntegrationStatusResult()
            state = data.get("connection_state")
            enabled = data.get("pairing_self_service_enabled")
            if state not in {"open", "connecting", "pairing", "disconnected", "logged_out", "error", "stopped", "disabled"} or not isinstance(enabled, bool):
                return IntegrationStatusResult()
            return IntegrationStatusResult(state, True, enabled)
        except (httpx.HTTPError, ValueError, OSError, json.JSONDecodeError):
            return IntegrationStatusResult()


__all__ = ["DeliveryResult", "IntegrationStatusResult", "WhatsAppDeliveryProvider",
           "WhatsAppPairingProvider", "WhatsAppStatusProvider", "normalize_brazilian_phone"]
