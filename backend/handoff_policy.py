"""Backend-only launch destinations. Empty allowlists deny every destination."""
import ipaddress
import json
import os
import re
from urllib.parse import urlsplit

from fastapi import HTTPException


_CONFIGURED_HANDOFF_MODULES = frozenset({"orders"})
_HOST_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


class HandoffOriginConfigurationError(ValueError):
    """The configured allowlist cannot be used safely."""


def _canonical_host(hostname: str) -> str:
    """Return an unambiguous, ASCII host or raise for an invalid hostname."""
    try:
        return str(ipaddress.ip_address(hostname))
    except ValueError:
        pass

    try:
        host = hostname.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise HandoffOriginConfigurationError() from exc
    if len(host) > 253 or not all(_HOST_LABEL_RE.fullmatch(label) for label in host.split(".")):
        raise HandoffOriginConfigurationError()
    return host


def _canonical_allowed_origin(value: object) -> str:
    """Parse one configured HTTPS origin into its sole comparison representation.

    A final slash and the default HTTPS port are semantically equivalent and are
    normalized. Whitespace is rejected rather than silently trimmed, so a typo in
    the environment cannot pass startup and later behave differently at runtime.
    """
    if not isinstance(value, str) or not value or value != value.strip() or any(char.isspace() for char in value):
        raise HandoffOriginConfigurationError()
    if "*" in value or "\\" in value:
        raise HandoffOriginConfigurationError()
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise HandoffOriginConfigurationError() from exc
    if (parsed.scheme.lower() != "https" or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.path not in ("", "/")
            or parsed.query or parsed.fragment or "%" in parsed.netloc):
        raise HandoffOriginConfigurationError()

    host = _canonical_host(parsed.hostname)
    rendered_host = f"[{host}]" if ":" in host else host
    return f"https://{rendered_host}" + (f":{port}" if port and port != 443 else "")


def allowed_handoff_origins(module: str) -> frozenset[str]:
    """Load, validate and canonicalize the complete handoff allowlist once.

    Only explicitly supported module keys are accepted. This prevents a typo such
    as ``Orders`` from becoming an alternate allowlist for ``orders``.
    """
    if module not in _CONFIGURED_HANDOFF_MODULES:
        raise HandoffOriginConfigurationError()
    try:
        configured = json.loads(os.environ.get("HANDOFF_ALLOWED_ORIGINS_JSON", "{}"))
    except (TypeError, json.JSONDecodeError) as exc:
        raise HandoffOriginConfigurationError() from exc
    if not isinstance(configured, dict) or set(configured) != _CONFIGURED_HANDOFF_MODULES:
        raise HandoffOriginConfigurationError()

    raw_origins = configured.get(module)
    if not isinstance(raw_origins, list) or not raw_origins:
        raise HandoffOriginConfigurationError()
    origins = frozenset(_canonical_allowed_origin(origin) for origin in raw_origins)
    if len(origins) != len(raw_origins):
        raise HandoffOriginConfigurationError()
    return origins


def _destination_origin(value: object) -> str:
    """Return the canonical origin of a complete handoff destination URL."""
    if not isinstance(value, str) or not value or any(ord(char) <= 32 or ord(char) == 127 for char in value):
        raise ValueError()
    if "\\" in value:
        raise ValueError()
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise ValueError() from exc
    if (parsed.scheme.lower() != "https" or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment or "%" in parsed.netloc):
        raise ValueError()
    host = _canonical_host(parsed.hostname)
    rendered_host = f"[{host}]" if ":" in host else host
    return f"https://{rendered_host}" + (f":{port}" if port and port != 443 else "")


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
        allowed_handoff_origins("orders")
    except HandoffOriginConfigurationError:
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
        if _destination_origin(value) not in allowed_handoff_origins(module):
            raise ValueError()
        return value
    except (HandoffOriginConfigurationError, TypeError, ValueError, AttributeError):
        raise HTTPException(400, "Destino de handoff inválido ou não autorizado")


def _safe_diagnostic_origin(value: object, *, allow_path: bool) -> str | None:
    """Return only a strictly normalized public origin suitable for a temporary log."""
    try:
        if allow_path:
            return _destination_origin(value)
        return _canonical_allowed_origin(value)
    except (HandoffOriginConfigurationError, TypeError, ValueError, AttributeError):
        return None


def launch_destination_diagnostics(value: str, module: str) -> dict[str, object]:
    """Build a log-safe diagnostic snapshot without exposing raw configuration or URLs.

    This does not participate in authorization or destination validation. Callers
    must keep it opt-in and use it only for controlled operational diagnosis.
    """
    present = "HANDOFF_ALLOWED_ORIGINS_JSON" in os.environ
    raw = os.environ.get("HANDOFF_ALLOWED_ORIGINS_JSON", "")
    json_valid = False
    safe_origins: list[str] = []
    try:
        json.loads(raw)
        json_valid = True
        safe_origins = sorted(allowed_handoff_origins(module))
    except (HandoffOriginConfigurationError, TypeError, json.JSONDecodeError):
        pass

    received_origin = _safe_diagnostic_origin(value, allow_path=True)
    return {
        "allowed_origins_present": present,
        "allowed_origins_json_valid": json_valid,
        "orders_origins": safe_origins,
        "received_origin": received_origin,
        "origin_match": bool(received_origin and received_origin in safe_origins),
    }
