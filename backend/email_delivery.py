"""Small, provider-specific delivery adapter for password reset e-mails."""

from html import escape
import logging

import httpx
from urllib.parse import quote


RESEND_EMAILS_URL = "https://api.resend.com/emails"
logger = logging.getLogger("dacot-hub")


def _resend_accepted(response: httpx.Response) -> bool:
    """A successful HTTP status alone is insufficient without Resend's email ID."""
    response.raise_for_status()
    payload = response.json()
    return isinstance(payload, dict) and isinstance(payload.get("id"), str) and bool(payload["id"].strip())


async def send_password_reset_email(
    to_email: str,
    token: str,
    *,
    frontend_url: str,
    resend_api_key: str,
    email_from_address: str,
    email_from_name: str,
    validity_hours: int = 1,
) -> bool:
    """Ask Resend to deliver a one-time password definition/reset link.

    Configuration and delivery failures deliberately return only ``False``.
    In particular, neither the token, reset URL, nor authorization value is
    ever written to a log message.
    """
    base = frontend_url.strip().rstrip("/")
    api_key = resend_api_key.strip()
    from_address = email_from_address.strip()
    from_name = email_from_name.strip() or "DACOT"
    if (
        not api_key
        or api_key.startswith("{")
        or not from_address
        or not base.startswith("https://")
    ):
        logger.error("Password reset email not configured")
        return False
    link = f"{base}/reset-password?token={token}"
    brand = escape(from_name)
    validity_text = "30 dias" if validity_hours == 720 else ("1 hora" if validity_hours == 1 else f"{validity_hours} horas")
    html = (
        '<table role="presentation" width="100%"><tr><td style="padding:24px;font-family:Arial,sans-serif">'
        f'<p>Defina ou redefina sua senha do {brand}.</p>'
        f'<p><a href="{escape(link)}">Definir minha senha</a></p>'
        f'<p>Este link expira em {validity_text} e pode ser usado apenas uma vez. '
        'Se você não solicitou, ignore este e-mail.</p>'
        f'<p style="font-size:12px;color:#888">Enviado por {brand}.</p>'
        '</td></tr></table>'
    )
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                RESEND_EMAILS_URL,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"from": f"{from_name} <{from_address}>", "to": [to_email],
                      "subject": f"Defina sua senha do {from_name}", "html": html},
            )
        return _resend_accepted(response)
    except Exception as exc:
        logger.error("Password reset email delivery failed: %s", type(exc).__name__)
        return False


async def send_owner_email_confirmation(
    to_email: str,
    token: str,
    *,
    frontend_url: str,
    resend_api_key: str,
    email_from_address: str,
    email_from_name: str,
) -> bool:
    """Ask Resend to deliver a one-time owner e-mail change confirmation.

    The proposed address is not made an authentication or recovery address
    until the recipient proves control of this credential.  Delivery failures
    intentionally reveal neither the token nor provider details.
    """
    base = frontend_url.strip().rstrip("/")
    api_key = resend_api_key.strip()
    from_address = email_from_address.strip()
    from_name = email_from_name.strip() or "DACOT"
    if not api_key or api_key.startswith("{") or not from_address or not base.startswith("https://"):
        logger.error("Owner e-mail confirmation not configured")
        return False
    link = f"{base}/confirm-owner-email?token={quote(token, safe='')}"
    brand = escape(from_name)
    html = (
        '<table role="presentation" width="100%"><tr><td style="padding:24px;font-family:Arial,sans-serif">'
        f'<p>Confirme o novo e-mail de acesso do proprietário no {brand}.</p>'
        f'<p><a href="{escape(link)}">Confirmar novo e-mail</a></p>'
        '<p>Este link expira em 24 horas e pode ser usado apenas uma vez. '
        'Até a confirmação, o e-mail anterior continua válido.</p>'
        '</td></tr></table>'
    )
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                RESEND_EMAILS_URL,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"from": f"{from_name} <{from_address}>", "to": [to_email],
                      "subject": f"Confirme seu novo e-mail do {from_name}", "html": html},
            )
        return _resend_accepted(response)
    except Exception as exc:
        logger.error("Owner e-mail confirmation delivery failed: %s", type(exc).__name__)
        return False

async def send_orders_first_access_email(
    to_email: str,
    token: str,
    *,
    orders_frontend_url: str,
    resend_api_key: str,
    email_from_address: str,
    email_from_name: str,
) -> bool:
    """Deliver a Pedidos first-access link without logging its credential."""
    base = orders_frontend_url.strip().rstrip("/")
    api_key = resend_api_key.strip()
    from_address = email_from_address.strip()
    from_name = email_from_name.strip() or "DACOT"
    if not api_key or api_key.startswith("{") or not from_address or not base.startswith("https://"):
        logger.error("Orders first-access email not configured")
        return False
    link = f"{base}/primeiro-acesso?token={quote(token, safe='')}"
    brand = escape(from_name)
    html = (
        '<table role="presentation" width="100%"><tr><td style="padding:24px;font-family:Arial,sans-serif">'
        '<p>Seu acesso ao Pedidos está pronto.</p>'
        f'<p><a href="{escape(link)}">Criar minha senha do Pedidos</a></p>'
        '<p>Este link expira em 24 horas e pode ser usado apenas uma vez. '
        'Se você não esperava este convite, ignore este e-mail.</p>'
        f'<p style="font-size:12px;color:#888">Enviado por {brand}.</p>'
        '</td></tr></table>'
    )
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                RESEND_EMAILS_URL,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"from": f"{from_name} <{from_address}>", "to": [to_email],
                      "subject": "Crie sua senha do DACOT Pedidos", "html": html},
            )
        return _resend_accepted(response)
    except Exception as exc:
        logger.error("Orders first-access email delivery failed: %s", type(exc).__name__)
        return False
