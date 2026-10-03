"""Small, provider-specific delivery adapter for password reset e-mails."""

from html import escape
import logging

import httpx


RESEND_EMAILS_URL = "https://api.resend.com/emails"
logger = logging.getLogger("dacot-hub")


async def send_password_reset_email(
    to_email: str,
    token: str,
    *,
    frontend_url: str,
    resend_api_key: str,
    email_from_address: str,
    email_from_name: str,
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
    html = (
        '<table role="presentation" width="100%"><tr><td style="padding:24px;font-family:Arial,sans-serif">'
        f'<p>Defina ou redefina sua senha do {brand}.</p>'
        f'<p><a href="{escape(link)}">Definir minha senha</a></p>'
        '<p>Este link expira em 1 hora e pode ser usado apenas uma vez. '
        'Se você não solicitou, ignore este e-mail.</p>'
        f'<p style="font-size:12px;color:#888">Enviado por {brand}.</p>'
        '</td></tr></table>'
    )
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                RESEND_EMAILS_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": f"{from_name} <{from_address}>",
                    "to": [to_email],
                    "subject": f"Defina sua senha do {from_name}",
                    "html": html,
                },
            )
        response.raise_for_status()
        return True
    except Exception as exc:
        # Exception strings can contain a request URL. Logging only its type
        # avoids leaking the reset token carried in the URL rendered above.
        logger.error("Password reset email delivery failed: %s", type(exc).__name__)
        return False
