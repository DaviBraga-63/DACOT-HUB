"""Security tests for the temporary, super-admin-only issuer diagnostic."""

import asyncio
import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import motor.motor_asyncio
import pytest
from fastapi import HTTPException, Response


@pytest.fixture
def hub(monkeypatch):
    backend = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(backend))
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.setenv("MONGO_URL", "mongodb://127.0.0.1:27017")
    monkeypatch.setenv("DB_NAME", "isolated_unit")
    monkeypatch.setenv("JWT_SECRET", "not-a-production-secret")
    monkeypatch.setattr(motor.motor_asyncio, "AsyncIOMotorClient", MagicMock())
    spec = importlib.util.spec_from_file_location("hub_handoff_diagnostics_test", backend / "server.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Response:
    def __init__(self, status_code=200, payload=None, json_error=None):
        self.status_code = status_code
        self.payload = payload
        self.json_error = json_error

    def json(self):
        if self.json_error:
            raise self.json_error
        return self.payload


class _Client:
    def __init__(self, calls, response=None, error=None, **options):
        self.calls = calls
        self.response = response
        self.error = error
        self.calls["options"] = options

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def get(self, url, *, headers):
        self.calls["url"] = url
        self.calls["headers"] = headers
        if self.error:
            raise self.error
        return self.response


def _install_orders_client(hub, monkeypatch, *, response=None, error=None):
    calls = {}
    monkeypatch.setenv("ORDERS_BACKEND_URL", "https://orders.example.test")
    monkeypatch.setattr(hub, "MODULE_ACCESS_KEYS", {hub.ORDERS_MODULE_KEY: "module-key"})
    monkeypatch.setattr(
        hub.httpx,
        "AsyncClient",
        lambda **options: _Client(calls, response=response, error=error, **options),
    )
    return calls


def test_handoff_runtime_diagnostics_is_opt_in_super_admin_only_and_sanitized(hub, monkeypatch):
    route = next(route for route in hub.app.routes if route.path == "/api/hub/handoff/runtime-diagnostics")
    assert any(dep.call is hub.get_super_admin for dep in route.dependant.dependencies)

    monkeypatch.delenv("HANDOFF_RUNTIME_DIAGNOSTICS", raising=False)
    with pytest.raises(HTTPException) as disabled:
        asyncio.run(hub.handoff_runtime_diagnostics(Response(), {"_id": "founder", "role": "super_admin"}))
    assert disabled.value.status_code == 404

    with pytest.raises(HTTPException) as denied:
        asyncio.run(hub.get_super_admin({"_id": "staff", "role": "admin"}))
    assert denied.value.status_code == 403

    monkeypatch.setenv("HANDOFF_RUNTIME_DIAGNOSTICS", "true")
    monkeypatch.setattr(hub, "HANDOFF_ISSUER", "dacot-hub")
    monkeypatch.setattr(hub, "_orders_issuer_matches_contract", AsyncMock(return_value=(True, True)))
    response = Response()
    result = asyncio.run(hub.handoff_runtime_diagnostics(response, {"_id": "founder", "role": "super_admin"}))
    assert result == {
        "hub_issuer_matches_contract": True,
        "orders_issuer_matches_contract": True,
        "orders_reachable": True,
    }
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "HANDOFF_ISSUER" not in str(result)

    monkeypatch.setattr(hub, "HANDOFF_ISSUER", "unexpected-value")
    mismatch = asyncio.run(hub.handoff_runtime_diagnostics(Response(), {"_id": "founder", "role": "super_admin"}))
    assert mismatch == {
        "hub_issuer_matches_contract": False,
        "orders_issuer_matches_contract": True,
        "orders_reachable": True,
    }

    monkeypatch.setattr(hub, "_orders_issuer_matches_contract", AsyncMock(return_value=(False, False)))
    unavailable = asyncio.run(hub.handoff_runtime_diagnostics(Response(), {"_id": "founder", "role": "super_admin"}))
    assert unavailable == {
        "hub_issuer_matches_contract": False,
        "orders_issuer_matches_contract": False,
        "orders_reachable": False,
    }


@pytest.mark.parametrize("response", [
    _Response(status_code=503, payload={"issuer_matches_contract": True}),
    _Response(payload=None, json_error=ValueError("invalid JSON")),
    _Response(payload={}),
    _Response(payload={"issuer_matches_contract": True, "unexpected": False}),
    _Response(payload={"issuer_matches_contract": "true"}),
])
def test_orders_issuer_diagnostic_fails_closed_for_invalid_responses(hub, monkeypatch, response):
    _install_orders_client(hub, monkeypatch, response=response)
    assert asyncio.run(hub._orders_issuer_matches_contract()) == (False, False)


@pytest.mark.parametrize("issuer_matches", [True, False])
def test_orders_issuer_diagnostic_uses_fixed_internal_contract(hub, monkeypatch, issuer_matches):
    calls = _install_orders_client(
        hub,
        monkeypatch,
        response=_Response(payload={"issuer_matches_contract": issuer_matches}),
    )
    assert asyncio.run(hub._orders_issuer_matches_contract()) == (True, issuer_matches)
    assert calls == {
        "options": {"timeout": 3.0, "follow_redirects": False, "trust_env": False},
        "url": "https://orders.example.test/api/internal/hub/handoff-runtime-diagnostics",
        "headers": {"X-Module-Key": "module-key"},
    }


def test_orders_issuer_diagnostic_hides_orders_unavailability(hub, monkeypatch):
    _install_orders_client(hub, monkeypatch, error=hub.httpx.ConnectError("unavailable"))
    assert asyncio.run(hub._orders_issuer_matches_contract()) == (False, False)
