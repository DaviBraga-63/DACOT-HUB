"""Backend-only launch destinations. Empty allowlist denies every destination."""
import json
import os
from urllib.parse import urlsplit

from fastapi import HTTPException


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
