"""Twilio SMS adapter for one-time DACOT access links.

Only provider state and non-sensitive identifiers leave this module. Message
bodies, destinations, credentials, and reset links are never logged.
"""

from dataclasses import dataclass
import logging
import re

import httpx

from phone_numbers import normalize_brazilian_mobile


logger = logging.getLogger("dacot-hub")
_TWILIO_ACCOUNT_SID = re.compile(r"^AC[0-9a-fA-F]{32}$")
_TWILIO_MESSAGING_SID = re.compile(r"^MG[0-9a-fA-F]{32}$")
_TWILIO_MESSAGE_SID = re.compile(r"^SM[0-9a-fA-F]{32}$")
_E164 = re.compile(r"^\+[1-9][0-9]{7,14}$")


@dataclass(frozen=True)
class SmsDeliveryResult:
    state: str
    http_status: int | None = None
    provider_message_id: str | None = None
    error_code: str | None = None


class SmsDeliveryProvider:
    def __init__(self, *, provider: str, account_sid: str, auth_token: str,
                 sender: str = "", messaging_service_sid: str = "", client_factory=None):
        self.provider = provider.strip().lower()
        self.account_sid = account_sid.strip()
        self.auth_token = auth_token.strip()
        self.sender = sender.strip()
        self.messaging_service_sid = messaging_service_sid.strip()
        self.client_factory = client_factory or httpx.AsyncClient

    async def send(self, *, number: str, message: str) -> SmsDeliveryResult:
        if (self.provider != "twilio" or not _TWILIO_ACCOUNT_SID.fullmatch(self.account_sid)
                or not self.auth_token or not message or len(message) > 1600
                or bool(self.sender) == bool(self.messaging_service_sid)
                or (self.messaging_service_sid and not _TWILIO_MESSAGING_SID.fullmatch(self.messaging_service_sid))):
            return SmsDeliveryResult("configuration_error")
        try:
            destination = normalize_brazilian_mobile(number)
        except ValueError:
            return SmsDeliveryResult("failed", error_code="invalid_destination")

        data = {"To": destination, "Body": message}
        if self.messaging_service_sid:
            data["MessagingServiceSid"] = self.messaging_service_sid
        else:
            if not _E164.fullmatch(self.sender):
                return SmsDeliveryResult("configuration_error", error_code="invalid_sender")
            data["From"] = self.sender

        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Messages.json"
        try:
            async with self.client_factory(timeout=10.0, follow_redirects=False, trust_env=False) as client:
                response = await client.post(url, data=data, auth=(self.account_sid, self.auth_token))
            try:
                payload = response.json()
            except ValueError:
                payload = {}
            if response.status_code == 201 and isinstance(payload, dict):
                sid = payload.get("sid")
                status = payload.get("status")
                if isinstance(sid, str) and _TWILIO_MESSAGE_SID.fullmatch(sid):
                    state = {
                        "accepted": "accepted", "scheduled": "accepted", "queued": "accepted",
                        "sending": "accepted", "sent": "sent", "delivered": "delivered",
                        "failed": "failed", "undelivered": "undelivered",
                    }.get(status)
                    if state:
                        provider_code = payload.get("error_code")
                        safe_code = str(provider_code) if isinstance(provider_code, int) or (
                            isinstance(provider_code, str) and provider_code.isdigit()
                        ) else None
                        return SmsDeliveryResult(state, response.status_code, sid, safe_code)
                return SmsDeliveryResult("failed", response.status_code, error_code="invalid_provider_response")
            code = payload.get("code") if isinstance(payload, dict) else None
            safe_code = str(code) if isinstance(code, int) or (isinstance(code, str) and code.isdigit()) else None
            return SmsDeliveryResult("failed", response.status_code, error_code=safe_code)
        except httpx.TimeoutException:
            return SmsDeliveryResult("unknown", error_code="timeout")
        except httpx.HTTPError as exc:
            return SmsDeliveryResult("unknown", error_code=type(exc).__name__)
        except Exception as exc:
            return SmsDeliveryResult("unknown", error_code=type(exc).__name__)
