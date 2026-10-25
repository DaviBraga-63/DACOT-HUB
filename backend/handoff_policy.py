"""Backend-only launch destinations. Empty allowlist denies every destination."""
import json
import os
from urllib.parse import urlsplit

from fastapi import HTTPException


def validate_handoff_configuration(secret: str, issuer: str, audiences: dict,
                                   version: int, module_access_keys: dict) -> None:
    """Fail closed at startup when the production handoff is incomplete."""
    if os.environ.get("APP_ENV", "production").strip().lower() != "production":
        return

    errors = []
    if not secret or len(secret) < 32:
        errors.append("HANDOFF_JWT_SECRET deve ter ao menos 32 caracteres")
    if not issuer.strip():
        errors.append("HANDOFF_ISSUER é obrigatório")
    if not audiences.get("orders"):
        errors.append("audiência do módulo orders é obrigatória")
    if version != 1:
        errors.append("HANDOFF_VERSION deve ser 1")
    if len(module_access_keys.get("orders", "")) < 32:
        errors.append("MODULE_API_KEY deve ter ao menos 32 caracteres")

    try:
        configured = json.loads(os.environ.get("HANDOFF_ALLOWED_ORIGINS_JSON", "{}"))
        origins = configured.get("orders")
        if not isinstance(origins, list) or not origins:
            raise ValueError()
        for origin in origins:
            parsed = urlsplit(origin)
            _ = parsed.port
            if (not isinstance(origin, str) or parsed.scheme != "https" or not parsed.hostname
                    or parsed.username is not None or parsed.password is not None
                    or parsed.path not in ("", "/") or parsed.query or parsed.fragment
                    or "*" in origin or "\\" in origin):
                raise ValueError()
    except (ValueError, TypeError, AttributeError, json.JSONDecodeError):
        errors.append("HANDOFF_ALLOWED_ORIGINS_JSON deve autorizar ao menos uma origem HTTPS exata para orders")

    if errors:
        raise RuntimeError("Configuração de handoff inválida: " + "; ".join(errors))


def orders_module_key():
    values = {os.environ[name] for name in ("MODULE_API_KEY", "ORDERS_MODULE_KEY") if os.environ.get(name)}
    if len(values) > 1:
        raise RuntimeError("MODULE_API_KEY and legacy ORDERS_MODULE_KEY disagree")
    return next(iter(values), "")


def validate_launch_url(value: str, module: str) -> str:
    try:
        allowed = json.loads(os.environ.get("HANDOFF_ALLOWED_ORIGINS_JSON", "{}"))
        origins = allowed.get(module, [])
        if not isinstance(origins, list) or not all(isinstance(x, str) for x in origins):
            raise ValueError()
        # Reject ambiguous browser parsing, redirect parameters and token fragments.
        if not value or any(ord(c) <= 32 or ord(c) == 127 for c in value) or "\\" in value:
            raise ValueError()
        parsed = urlsplit(value)
        if not parsed.hostname or parsed.username is not None or parsed.password is not None:
            raise ValueError()
        if parsed.query or parsed.fragment or "%" in parsed.netloc:
            raise ValueError()
        port = parsed.port  # validates invalid/out-of-range ports
        local = os.environ.get("APP_ENV", "production") == "development"
        if parsed.scheme != "https" and not (
            local and parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        ):
            raise ValueError()
        host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
        default_port = 443 if parsed.scheme == "https" else 80
        origin = f"{parsed.scheme}://{host}" + (f":{port}" if port and port != default_port else "")
        if origin not in origins:
            raise ValueError()
        return value
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(400, "Destino de handoff inválido ou não autorizado")


def _safe_diagnostic_origin(value: object, *, allow_path: bool) -> str | None:
    """Return only a strictly normalized public origin suitable for a temporary log."""
    if not isinstance(value, str) or not value or any(ord(char) <= 32 or ord(char) == 127 for char in value):
        return None
    if "\\" in value or "*" in value:
        return None
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except (ValueError, TypeError, AttributeError):
        return None
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment or "%" in parsed.netloc):
        return None
    if not allow_path and parsed.path not in ("", "/"):
        return None
    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    return f"https://{host}" + (f":{port}" if port and port != 443 else "")


def launch_destination_diagnostics(value: str, module: str) -> dict[str, object]:
    """Build a log-safe diagnostic snapshot without exposing raw configuration or URLs.

    This does not participate in authorization or destination validation.  Callers
    must keep it opt-in and use it only for controlled operational diagnosis.
    """
    present = "HANDOFF_ALLOWED_ORIGINS_JSON" in os.environ
    raw = os.environ.get("HANDOFF_ALLOWED_ORIGINS_JSON", "")
    json_valid = False
    configured_origins: list[str] = []
    try:
        configured = json.loads(raw)
        json_valid = True
        if isinstance(configured, dict) and isinstance(configured.get(module), list):
            configured_origins = configured[module]
    except (TypeError, json.JSONDecodeError):
        pass

    received_origin = _safe_diagnostic_origin(value, allow_path=True)
    safe_origins = [
        origin for candidate in configured_origins
        if (origin := _safe_diagnostic_origin(candidate, allow_path=False)) is not None
    ]
    return {
        "allowed_origins_present": present,
        "allowed_origins_json_valid": json_valid,
        "orders_origins": safe_origins,
        "received_origin": received_origin,
        "origin_match": bool(received_origin and received_origin in configured_origins),
    }
