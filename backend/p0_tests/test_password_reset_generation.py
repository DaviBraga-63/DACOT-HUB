"""Unit tests with fake collections; no database or email provider is contacted."""

import asyncio
import hashlib
import importlib.util
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import motor.motor_asyncio
import pytest
from bson import ObjectId
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
    spec = importlib.util.spec_from_file_location("hub_reset_test", backend / "server.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    async def run_mock_transaction(callback):
        return await callback(None)
    monkeypatch.setattr(module, "_whatsapp_transaction", run_mock_transaction)
    return module


def test_expiration_and_generation_for_new_tokens(hub, monkeypatch):
    users = SimpleNamespace(update_one=AsyncMock(return_value=SimpleNamespace(matched_count=1)))
    tokens = SimpleNamespace(insert_one=AsyncMock())
    monkeypatch.setattr(hub, "db", SimpleNamespace(tenant_users=users, password_reset_tokens=tokens))
    uid = str(ObjectId())
    before = hub.now_utc()
    first = asyncio.run(hub._issue_password_reset(uid, "owner@example.test", "restaurant", first_access=True))
    first_doc = tokens.insert_one.call_args.args[0]
    assert timedelta(days=29, hours=23) < first_doc["expires_at"] - before <= timedelta(days=30, seconds=2)
    assert first_doc["token_hash"] == hashlib.sha256(first.encode()).hexdigest()
    assert first not in str(first_doc)
    asyncio.run(hub._issue_password_reset(uid, "owner@example.test", "restaurant"))
    recovery_doc = tokens.insert_one.call_args.args[0]
    assert timedelta(hours=23) < recovery_doc["expires_at"] - before <= timedelta(days=1, seconds=2)
    assert first_doc["generation"] != recovery_doc["generation"]
    assert users.update_one.call_args.args[1]["$set"]["password_reset_generation"] == recovery_doc["generation"]


def test_reset_requires_token_generation_and_revokes_sessions(hub, monkeypatch):
    uid, tid = ObjectId(), ObjectId()
    token_doc = {"user_id": str(uid), "user_type": "restaurant", "email": "x@example.test", "generation": "gen-current"}
    users = SimpleNamespace(find_one=AsyncMock(return_value={"_id": uid, "tenant_id": str(tid)}),
                            update_one=AsyncMock(return_value=SimpleNamespace(matched_count=1)))
    tokens = SimpleNamespace(find_one_and_update=AsyncMock(return_value=token_doc))
    db = SimpleNamespace(tenant_users=users, password_reset_tokens=tokens,
                         tenants=SimpleNamespace(find_one=AsyncMock(return_value={"_id": tid})),
                         login_attempts=SimpleNamespace(delete_many=AsyncMock()))
    monkeypatch.setattr(hub, "db", db)
    revoke = AsyncMock()
    monkeypatch.setattr(hub, "revoke_user_sessions", revoke)
    monkeypatch.setattr(hub, "hash_password", lambda _: "hashed")
    assert asyncio.run(hub.reset(hub.ResetIn(token="synthetic", password="long-enough"))) == {"ok": True}
    assert users.update_one.call_args.args[0]["password_reset_generation"] == "gen-current"
    revoke.assert_awaited_once()
    users.update_one.return_value = SimpleNamespace(matched_count=0)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(hub.reset(hub.ResetIn(token="synthetic", password="long-enough")))
    assert exc.value.status_code == 400
    revoke.assert_awaited_once()


def test_expired_or_already_used_token_is_rejected(hub, monkeypatch):
    tokens = SimpleNamespace(find_one_and_update=AsyncMock(return_value=None))
    monkeypatch.setattr(hub, "db", SimpleNamespace(password_reset_tokens=tokens))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(hub.reset(hub.ResetIn(token="synthetic", password="long-enough")))
    assert exc.value.status_code == 400
    assert tokens.find_one_and_update.call_args.args[0]["used"] is False
    assert "$gt" in tokens.find_one_and_update.call_args.args[0]["expires_at"]


def test_replacement_invalidates_previous_link_and_new_link_is_single_use(hub, monkeypatch):
    uid = ObjectId()
    user = {"_id": uid, "deleted_at": None}
    stored = []

    async def update(query, update):
        if any(user.get(key) != value for key, value in query.items()):
            return SimpleNamespace(matched_count=0)
        if isinstance(update, list):
            user.update({key: value["$literal"] for key, value in update[0]["$set"].items() if "$literal" in value})
        else:
            user.update(update["$set"])
        return SimpleNamespace(matched_count=1)

    async def insert(doc):
        stored.append(doc)

    async def claim(query, _update):
        for doc in stored:
            if (doc["token_hash"] == query["token_hash"] and not doc["used"]
                    and doc["expires_at"] > query["expires_at"]["$gt"]):
                doc["used"] = True
                return doc
        return None

    users = SimpleNamespace(update_one=update)
    tokens = SimpleNamespace(insert_one=insert, find_one_and_update=claim)
    db = SimpleNamespace(hub_users=users, password_reset_tokens=tokens,
                         login_attempts=SimpleNamespace(delete_many=AsyncMock()))
    monkeypatch.setattr(hub, "db", db)
    monkeypatch.setattr(hub, "revoke_user_sessions", AsyncMock())
    monkeypatch.setattr(hub, "hash_password", lambda _: "hashed")
    first = asyncio.run(hub._issue_password_reset(str(uid), "staff@example.test", "staff"))
    second = asyncio.run(hub._issue_password_reset(str(uid), "staff@example.test", "staff"))
    with pytest.raises(HTTPException):
        asyncio.run(hub.reset(hub.ResetIn(token=first, password="long-enough")))
    assert asyncio.run(hub.reset(hub.ResetIn(token=second, password="long-enough"))) == {"ok": True}
    with pytest.raises(HTTPException):
        asyncio.run(hub.reset(hub.ResetIn(token=second, password="long-enough")))


def test_only_super_admin_can_modify_contact_and_audit_is_atomic(hub, monkeypatch):
    tenant_id = ObjectId()
    admin = {"_id": "staff-id", "role": "admin", "email": "admin@example.test"}
    tenants = SimpleNamespace(
        update_one=AsyncMock(return_value=SimpleNamespace(matched_count=1)),
        find_one=AsyncMock(return_value={"_id": tenant_id, "name": "Test"}),
    )
    monkeypatch.setattr(hub, "db", SimpleNamespace(tenants=tenants))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(hub.patch_tenant(str(tenant_id), hub.TenantPatch(whatsapp_phone="11912345678"), admin))
    assert exc.value.status_code == 403
    tenants.update_one.assert_not_awaited()
    super_admin = {**admin, "role": "super_admin"}
    asyncio.run(hub.patch_tenant(str(tenant_id), hub.TenantPatch(whatsapp_phone="11912345678"), super_admin))
    mutation = tenants.update_one.call_args.args[1]
    assert mutation["$set"]["whatsapp_phone"] == "+5511912345678"
    assert mutation["$push"]["whatsapp_audit"]["actor_id"] == "staff-id"
    assert mutation["$push"]["whatsapp_audit"]["at"]
    assert asyncio.run(hub.get_super_admin(super_admin)) == super_admin
    with pytest.raises(HTTPException):
        asyncio.run(hub.get_super_admin(admin))
    asyncio.run(hub.patch_tenant(str(tenant_id), hub.TenantPatch(notes="updated"), admin))
    assert tenants.update_one.call_args.args[1]["$set"]["notes"] == "updated"


def test_tenant_creation_routes_require_super_admin(hub):
    for path in ("/hub/tenants", "/hub/tenants/onboard"):
        route = next(route for route in hub.api_router.routes
                     if route.path == "/api" + path and "POST" in route.methods)
        assert any(dep.call is hub.get_super_admin for dep in route.dependant.dependencies)


def test_whatsapp_link_is_bound_to_version_and_rotation_rejects_it(hub, monkeypatch):
    uid, tid = ObjectId(), ObjectId()
    user = {"_id": uid, "tenant_id": str(tid), "whatsapp_binding_version": "new-version"}
    token = {"user_id": str(uid), "user_type": "restaurant", "email": "owner@example.test",
             "generation": "generation", "whatsapp_binding_version": "old-version"}
    async def update(query, _mutation):
        assert query["whatsapp_binding_version"] == "old-version"
        return SimpleNamespace(matched_count=int(query["whatsapp_binding_version"] == user["whatsapp_binding_version"]))
    db = SimpleNamespace(
        tenant_users=SimpleNamespace(find_one=AsyncMock(return_value=user), update_one=update),
        tenants=SimpleNamespace(find_one=AsyncMock(return_value={"_id": tid})),
        password_reset_tokens=SimpleNamespace(find_one_and_update=AsyncMock(return_value=token)),
    )
    monkeypatch.setattr(hub, "db", db)
    monkeypatch.setattr(hub, "hash_password", lambda _: "hashed")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(hub.reset(hub.ResetIn(token="synthetic", password="long-enough")))
    assert exc.value.status_code == 400


def test_whatsapp_issue_requires_current_binding(hub, monkeypatch):
    users = SimpleNamespace(update_one=AsyncMock(return_value=SimpleNamespace(matched_count=0)))
    tokens = SimpleNamespace(insert_one=AsyncMock())
    monkeypatch.setattr(hub, "db", SimpleNamespace(tenant_users=users, password_reset_tokens=tokens))
    with pytest.raises(HTTPException):
        asyncio.run(hub._issue_password_reset(str(ObjectId()), "owner@example.test", "restaurant", whatsapp_version="outdated"))
    assert users.update_one.call_args.args[0]["whatsapp_binding_version"] == "outdated"
    tokens.insert_one.assert_not_awaited()


def test_binding_requires_super_admin_and_scopes_user_to_tenant(hub, monkeypatch):
    route = next(route for route in hub.api_router.routes if route.path == "/api/hub/tenants/{tid}/whatsapp")
    assert any(dep.call is hub.get_super_admin for dep in route.dependant.dependencies)
    tid, uid = str(ObjectId()), str(ObjectId())
    users = SimpleNamespace(find_one=AsyncMock(return_value=None), update_one=AsyncMock())
    monkeypatch.setattr(hub, "db", SimpleNamespace(tenant_users=users))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(hub.bind_whatsapp(tid, hub.WhatsAppBindingIn(user_id=uid, phone="11912345678"), {"_id": "actor"}))
    assert exc.value.status_code == 404
    assert users.find_one.call_args.args[0]["tenant_id"] == tid
    users.update_one.assert_not_awaited()


def test_forgot_whatsapp_only_sends_to_bound_user_and_response_is_generic(hub, monkeypatch):
    uid, tid = ObjectId(), ObjectId()
    account = {"_id": uid, "email": "owner@example.com", "tenant_id": str(tid), "status": "active",
               "whatsapp_number": "+5511912345678", "whatsapp_binding_version": "version"}
    counters = SimpleNamespace(find_one_and_update=AsyncMock(return_value={"count": 1}))
    users = SimpleNamespace(find_one=AsyncMock(return_value=account))
    tenant = {"_id": tid, "whatsapp_user_id": str(uid)}
    tenants = SimpleNamespace(find_one=AsyncMock(return_value=tenant))
    monkeypatch.setattr(hub, "db", SimpleNamespace(password_reset_requests=counters,
                        hub_users=SimpleNamespace(find_one=AsyncMock(return_value=None)),
                        tenant_users=users, tenants=tenants))
    issue = AsyncMock(return_value="synthetic-token")
    monkeypatch.setattr(hub, "_issue_password_reset", issue)
    allow = AsyncMock(return_value=True)
    monkeypatch.setattr(hub, "_allow_recovery_request", allow)
    request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"), headers={})
    tasks = hub.BackgroundTasks()
    response = asyncio.run(hub.forgot(hub.ForgotIn(email=account["email"], channel="whatsapp"), tasks, request))
    assert response == hub.GENERIC_RESET_RESPONSE
    assert issue.call_args.kwargs["whatsapp_version"] == "version"
    assert len(tasks.tasks) == 1
    tenant["whatsapp_user_id"] = str(ObjectId())
    issue.reset_mock()
    tasks = hub.BackgroundTasks()
    assert asyncio.run(hub.forgot(hub.ForgotIn(email=account["email"], channel="whatsapp"), tasks, request)) == response
    issue.assert_not_awaited()
    assert not tasks.tasks
    allow.return_value = False
    assert asyncio.run(hub.forgot(hub.ForgotIn(email=account["email"], channel="whatsapp"), tasks, request)) == response
    issue.assert_not_awaited()


def test_recovery_ip_ignores_untrusted_forwarding_and_resolves_trusted_chain(hub, monkeypatch):
    request = SimpleNamespace(client=SimpleNamespace(host="192.0.2.5"),
                              headers={"x-forwarded-for": "198.51.100.5, 192.0.2.9"})
    monkeypatch.delenv("RECOVERY_TRUSTED_PROXY_CIDRS", raising=False)
    assert hub._recovery_client_ip(request) == "192.0.2.5"
    monkeypatch.setenv("RECOVERY_TRUSTED_PROXY_CIDRS", "192.0.2.0/24")
    assert hub._recovery_client_ip(request) == "198.51.100.5"


def test_invalid_status_never_changes_whatsapp(hub, monkeypatch):
    users = SimpleNamespace(update_one=AsyncMock())
    tenants = SimpleNamespace(update_one=AsyncMock())
    monkeypatch.setattr(hub, "db", SimpleNamespace(tenant_users=users, tenants=tenants))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(hub.patch_tenant(str(ObjectId()), hub.TenantPatch(whatsapp_phone="11912345678", status="bad"),
                                     {"_id": "actor", "role": "super_admin"}))
    assert exc.value.status_code == 400
    users.update_one.assert_not_awaited()
    tenants.update_one.assert_not_awaited()


def test_pairing_code_requires_super_admin_route_and_never_persists_phone_or_code(hub, monkeypatch):
    route = next(route for route in hub.app.routes if route.path == "/api/hub/whatsapp/pairing-code")
    assert any(dep.call is hub.get_super_admin for dep in route.dependant.dependencies)
    actor_id = str(ObjectId())
    users = SimpleNamespace(find_one=AsyncMock(return_value={"password_hash": "stored", "name": "Founder"}))
    monkeypatch.setattr(hub, "db", SimpleNamespace(hub_users=users))
    monkeypatch.setenv("WHATSAPP_PAIRING_SELF_SERVICE_ENABLED", "true")
    monkeypatch.setattr(hub, "verify_password", lambda supplied, stored: supplied == "correct" and stored == "stored")
    monkeypatch.setattr(hub, "_allow_pairing_code_request", AsyncMock(return_value=True))
    request_code = AsyncMock(return_value="ABCD1234")
    monkeypatch.setattr(hub, "_request_gateway_pairing_code", request_code)
    audit = AsyncMock()
    monkeypatch.setattr(hub, "log_activity", audit)
    response = Response()
    result = asyncio.run(hub.request_whatsapp_pairing_code(
        hub.WhatsAppPairingCodeIn(phone="11912345678", password="correct"), response,
        {"_id": actor_id, "role": "super_admin"},
    ))
    assert result == {"code": "ABCD1234"}
    assert response.headers["cache-control"] == "no-store"
    assert request_code.call_args.args[0] == "+5511912345678"
    assert "11912345678" not in str(audit.call_args.kwargs)
    assert "ABCD1234" not in str(audit.call_args.kwargs)
    monkeypatch.setenv("WHATSAPP_PAIRING_SELF_SERVICE_ENABLED", "false")
    with pytest.raises(HTTPException) as disabled:
        asyncio.run(hub.request_whatsapp_pairing_code(
            hub.WhatsAppPairingCodeIn(phone="11912345678", password="correct"), Response(),
            {"_id": actor_id, "role": "super_admin"},
        ))
    assert disabled.value.status_code == 404


def test_whatsapp_status_requires_super_admin_and_fails_closed_for_gateway_unavailability(hub, monkeypatch):
    route = next(route for route in hub.app.routes if route.path == "/api/hub/whatsapp/status")
    assert any(dep.call is hub.get_super_admin for dep in route.dependant.dependencies)
    with pytest.raises(HTTPException) as denied:
        asyncio.run(hub.get_super_admin({"_id": "staff", "role": "admin"}))
    assert denied.value.status_code == 403

    monkeypatch.setenv("WHATSAPP_PAIRING_SELF_SERVICE_ENABLED", "true")
    monkeypatch.setattr(hub, "_get_whatsapp_integration_status", AsyncMock(return_value=SimpleNamespace(
        connection_state="open", gateway_reachable=True, pairing_self_service_enabled=True,
        connected_account_phone="+5511912345678",
    )))
    response = Response()
    result = asyncio.run(hub.whatsapp_integration_status(response, {"_id": "founder", "role": "super_admin"}))
    assert result == {
        "connection_state": "open",
        "gateway_reachable": True,
        "pairing_self_service_enabled": True,
        "connected_account_phone": "+5511912345678",
    }
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"

    monkeypatch.setattr(hub, "_get_whatsapp_integration_status", AsyncMock(return_value=SimpleNamespace(
        connection_state="disconnected", gateway_reachable=False, pairing_self_service_enabled=True,
        connected_account_phone=None,
    )))
    unavailable = asyncio.run(hub.whatsapp_integration_status(Response(), {"_id": "founder", "role": "super_admin"}))
    assert unavailable == {
        "connection_state": "unavailable",
        "gateway_reachable": False,
        "pairing_self_service_enabled": False,
        "connected_account_phone": None,
    }

    monkeypatch.setenv("WHATSAPP_PAIRING_SELF_SERVICE_ENABLED", "false")
    monkeypatch.setattr(hub, "_get_whatsapp_integration_status", AsyncMock(return_value=SimpleNamespace(
        connection_state="open", gateway_reachable=True, pairing_self_service_enabled=True,
        connected_account_phone=None,
    )))
    blocked = asyncio.run(hub.whatsapp_integration_status(Response(), {"_id": "founder", "role": "super_admin"}))
    assert blocked["pairing_self_service_enabled"] is False
    assert blocked["connected_account_phone"] is None
