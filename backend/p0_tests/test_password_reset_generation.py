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
    monkeypatch.setattr(module, "_phone_transaction", run_mock_transaction)
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


def _login_context(hub, monkeypatch, *, failures, password_valid):
    uid = ObjectId()
    staff = {"_id": uid, "email": "staff@example.com", "name": "Staff", "role": "admin",
             "password_hash": "synthetic-hash", "token_version": 0, "active": True, "deleted_at": None}
    users = SimpleNamespace(find_one=AsyncMock(return_value=staff), update_one=AsyncMock())
    attempts = SimpleNamespace(count_documents=AsyncMock(return_value=failures), insert_one=AsyncMock())
    activity = SimpleNamespace(insert_one=AsyncMock())
    monkeypatch.setattr(hub, "db", SimpleNamespace(
        hub_users=users, tenant_users=SimpleNamespace(find_one=AsyncMock()),
        login_attempts=attempts, activity_log=activity,
    ))
    monkeypatch.setattr(hub, "_client_ip", lambda _request: "198.51.100.40")
    monkeypatch.setattr(hub, "verify_password", lambda *_: password_valid)
    monkeypatch.setattr(hub, "valid_tab_session_id", lambda _value: True)
    monkeypatch.setattr(hub, "new_browser_binding", lambda: "synthetic-browser-binding")
    create_session = AsyncMock()
    monkeypatch.setattr(hub, "create_session", create_session)
    request = SimpleNamespace(headers={hub.TAB_SESSION_HEADER: "synthetic-tab-session"}, cookies={})
    return staff, attempts, activity, create_session, request


def test_login_rate_limit_records_fiftieth_failure_then_limits_next(hub, monkeypatch):
    _, attempts, _, _, request = _login_context(hub, monkeypatch, failures=49, password_valid=False)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(hub.login(hub.LoginIn(email="staff@example.com", password="wrong"), request, Response()))
    assert exc.value.status_code == 401
    attempts.insert_one.assert_awaited_once()
    assert attempts.insert_one.await_args.args[0]["success"] is False

    attempts.insert_one.reset_mock()
    attempts.count_documents.return_value = 50
    with pytest.raises(HTTPException) as exc:
        asyncio.run(hub.login(hub.LoginIn(email="staff@example.com", password="wrong"), request, Response()))
    assert exc.value.status_code == 429
    attempts.insert_one.assert_not_awaited()


def test_correct_login_is_not_blocked_by_prior_origin_failures(hub, monkeypatch):
    _, attempts, activity, create_session, request = _login_context(
        hub, monkeypatch, failures=50, password_valid=True)
    result = asyncio.run(hub.login(
        hub.LoginIn(email="staff@example.com", password="correct"), request, Response()))
    assert result["email"] == "staff@example.com"
    attempts.count_documents.assert_not_awaited()
    attempts.insert_one.assert_not_awaited()
    create_session.assert_awaited_once()
    activity.insert_one.assert_awaited_once()


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


def test_generic_tenant_patch_cannot_activate_mobile_recovery(hub, monkeypatch):
    tenant_id = ObjectId()
    admin = {"_id": "staff-id", "role": "admin", "email": "admin@example.test"}
    tenants = SimpleNamespace(
        update_one=AsyncMock(return_value=SimpleNamespace(matched_count=1)),
        find_one=AsyncMock(return_value={"_id": tenant_id, "name": "Test"}),
    )
    monkeypatch.setattr(hub, "db", SimpleNamespace(tenants=tenants))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(hub.patch_tenant(str(tenant_id), hub.TenantPatch(mobile_phone="11912345678"), admin))
    assert exc.value.status_code == 400
    tenants.update_one.assert_not_awaited()
    super_admin = {**admin, "role": "super_admin"}
    with pytest.raises(HTTPException) as exc:
        asyncio.run(hub.patch_tenant(str(tenant_id), hub.TenantPatch(mobile_phone="11912345678"), super_admin))
    assert exc.value.status_code == 400
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


def test_whatsapp_pairing_routes_require_super_admin_and_default_off(hub, monkeypatch):
    for path in ("/api/hub/whatsapp/status", "/api/hub/whatsapp/pairing-code"):
        route = next(route for route in hub.app.routes if route.path == path)
        assert any(dep.call is hub.get_super_admin for dep in route.dependant.dependencies)
    monkeypatch.delenv("WHATSAPP_PAIRING_SELF_SERVICE_ENABLED", raising=False)
    assert not hub._pairing_self_service_enabled()
    monkeypatch.setenv("WHATSAPP_PAIRING_SELF_SERVICE_ENABLED", "true")
    assert hub._pairing_self_service_enabled()


def test_phone_link_is_bound_to_version_and_rotation_rejects_it(hub, monkeypatch):
    uid, tid = ObjectId(), ObjectId()
    user = {"_id": uid, "tenant_id": str(tid), "phone_binding_version": "new-version"}
    token = {"user_id": str(uid), "user_type": "restaurant", "email": "owner@example.test",
             "generation": "generation", "phone_binding_version": "old-version"}
    async def update(query, _mutation):
        assert query["$or"] == [{"phone_binding_version": "old-version"},
                               {"whatsapp_binding_version": "old-version"}]
        return SimpleNamespace(matched_count=int(user["phone_binding_version"] == "old-version"))
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


def test_phone_issue_requires_current_binding(hub, monkeypatch):
    users = SimpleNamespace(update_one=AsyncMock(return_value=SimpleNamespace(matched_count=0)))
    tokens = SimpleNamespace(insert_one=AsyncMock())
    monkeypatch.setattr(hub, "db", SimpleNamespace(tenant_users=users, password_reset_tokens=tokens))
    with pytest.raises(HTTPException):
        asyncio.run(hub._issue_password_reset(str(ObjectId()), "owner@example.test", "restaurant",
                                              phone_binding_version="outdated"))
    assert users.update_one.call_args.args[0]["$or"][0]["phone_binding_version"] == "outdated"
    tokens.insert_one.assert_not_awaited()


def test_phone_binding_requires_super_admin_and_scopes_user_to_tenant(hub, monkeypatch):
    route = next(route for route in hub.app.routes if route.path == "/api/hub/tenants/{tid}/phone")
    assert any(dep.call is hub.get_super_admin for dep in route.dependant.dependencies)
    tid, uid = str(ObjectId()), str(ObjectId())
    users = SimpleNamespace(find_one=AsyncMock(return_value=None), update_one=AsyncMock())
    tenants = SimpleNamespace(find_one=AsyncMock(return_value={"_id": ObjectId(tid), "portal_owner_user_id": uid}))
    monkeypatch.setattr(hub, "db", SimpleNamespace(tenant_users=users, tenants=tenants))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(hub.bind_phone(tid, hub.PhoneBindingIn(user_id=uid, phone="11912345678"), {"_id": "actor"}))
    assert exc.value.status_code == 409
    assert users.find_one.call_args.args[0]["tenant_id"] == tid
    users.update_one.assert_not_awaited()


def test_owner_whatsapp_change_stays_pending_until_the_link_is_confirmed(hub, monkeypatch):
    tid, uid = str(ObjectId()), ObjectId()
    owner = {"_id": uid, "tenant_id": tid, "email": "owner@example.test", "status": "active"}
    tenant = {"_id": ObjectId(tid), "portal_owner_user_id": str(uid), "mobile_phone": "+5511911111111"}
    confirmations = SimpleNamespace(update_many=AsyncMock(), insert_one=AsyncMock(), delete_one=AsyncMock())
    users = SimpleNamespace(find_one=AsyncMock(side_effect=[owner, None]), update_one=AsyncMock())
    tenants = SimpleNamespace(find_one=AsyncMock(return_value=tenant), update_one=AsyncMock())
    monkeypatch.setattr(hub, "db", SimpleNamespace(
        tenants=tenants, tenant_users=users, hub_users=SimpleNamespace(find_one=AsyncMock(return_value=None)),
        owner_contact_confirmations=confirmations,
    ))
    monkeypatch.setattr(hub, "_owner_contact_confirmation_allowed", AsyncMock(return_value=True))
    monkeypatch.setattr(hub, "_send_whatsapp_reset", AsyncMock(return_value=hub.DeliveryResult.ACCEPTED))
    monkeypatch.setattr(hub, "log_activity", AsyncMock())
    result = asyncio.run(hub.request_owner_whatsapp_change(
        tid, hub.OwnerWhatsAppChangeIn(phone="11912345678"),
        {"_id": "staff", "email": "staff@example.test", "name": "Staff", "role": "super_admin"},
    ))
    assert result == {"state": "confirmation_requested"}
    doc = confirmations.insert_one.await_args.args[0]
    assert doc["kind"] == "whatsapp" and doc["proposed_value"] == "+5511912345678"
    assert len(doc["token_hash"]) == 64 and "11912345678" not in doc["token_hash"]
    users.update_one.assert_not_awaited()
    tenants.update_one.assert_not_awaited()


def test_owner_email_change_does_not_replace_login_until_confirmed(hub, monkeypatch):
    tid, uid = str(ObjectId()), ObjectId()
    owner = {"_id": uid, "tenant_id": tid, "email": "old@example.com", "status": "active"}
    tenant = {"_id": ObjectId(tid), "portal_owner_user_id": str(uid)}
    confirmations = SimpleNamespace(update_many=AsyncMock(), insert_one=AsyncMock(), delete_one=AsyncMock())
    async def find_user(query):
        return owner if query.get("_id") == uid else None
    users = SimpleNamespace(find_one=AsyncMock(side_effect=find_user), update_one=AsyncMock())
    monkeypatch.setattr(hub, "db", SimpleNamespace(
        tenants=SimpleNamespace(find_one=AsyncMock(return_value=tenant), update_one=AsyncMock()),
        tenant_users=users, hub_users=SimpleNamespace(find_one=AsyncMock(return_value=None)),
        owner_contact_confirmations=confirmations,
    ))
    monkeypatch.setattr(hub, "_owner_contact_confirmation_allowed", AsyncMock(return_value=True))
    monkeypatch.setattr(hub, "send_owner_email_confirmation", AsyncMock(return_value=True))
    monkeypatch.setattr(hub, "log_activity", AsyncMock())
    result = asyncio.run(hub.request_owner_email_change(
        tid, hub.OwnerEmailChangeIn(email="new@example.com"),
        {"_id": "staff", "email": "staff@example.com", "name": "Staff", "role": "super_admin"},
    ))
    assert result == {"state": "confirmation_sent"}
    assert confirmations.insert_one.await_args.args[0]["proposed_value"] == "new@example.com"
    users.update_one.assert_not_awaited()


def test_confirmed_owner_whatsapp_binds_only_the_portal_owner_and_revokes_sessions(hub, monkeypatch):
    tid, uid = str(ObjectId()), ObjectId()
    owner = {"_id": uid, "tenant_id": tid, "email": "owner@example.com", "name": "Owner", "status": "active"}
    tenant = {"_id": ObjectId(tid), "portal_owner_user_id": str(uid)}
    users = SimpleNamespace(find_one=AsyncMock(side_effect=[owner, None]),
                            update_one=AsyncMock(return_value=SimpleNamespace(matched_count=1)))
    tenants = SimpleNamespace(find_one=AsyncMock(return_value=tenant), update_one=AsyncMock())
    monkeypatch.setattr(hub, "db", SimpleNamespace(tenant_users=users, tenants=tenants))
    monkeypatch.setattr(hub, "_consume_owner_contact_confirmation", AsyncMock(return_value={
        "tenant_id": tid, "owner_user_id": str(uid), "proposed_value": "+5511912345678", "first_access": False,
    }))
    revoke = AsyncMock()
    monkeypatch.setattr(hub, "revoke_user_sessions", revoke)
    monkeypatch.setattr(hub, "log_activity", AsyncMock())
    result = asyncio.run(hub.confirm_owner_whatsapp(hub.OwnerContactConfirmationIn(token="x" * 32)))
    assert result == {"ok": True, "first_access_delivery": None}
    mutation = users.update_one.await_args.args[1][0]["$set"]
    assert mutation["phone_number"]["$literal"] == "+5511912345678"
    assert "phone_binding_version" in mutation
    assert tenants.update_one.await_args.args[1]["$set"]["phone_user_id"] == str(uid)
    revoke.assert_awaited_once_with(hub.db, user_id=str(uid), user_type="restaurant", reason="owner_whatsapp_changed")


def test_forgot_whatsapp_only_sends_to_bound_user_and_response_is_generic(hub, monkeypatch):
    uid, tid = ObjectId(), ObjectId()
    account = {"_id": uid, "email": "owner@example.com", "tenant_id": str(tid), "status": "active",
               "phone_number": "+5511912345678", "phone_binding_version": "version"}
    counters = SimpleNamespace(find_one_and_update=AsyncMock(return_value={"count": 1}))
    users = SimpleNamespace(find_one=AsyncMock(return_value=account))
    tenants = SimpleNamespace(find_one=AsyncMock(return_value={"_id": tid, "phone_user_id": str(uid)}))
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
    assert issue.call_args.kwargs["phone_binding_version"] == "version"
    assert len(tasks.tasks) == 1
    tenants.find_one.return_value = {"_id": tid, "phone_user_id": str(ObjectId())}
    issue.reset_mock()
    tasks = hub.BackgroundTasks()
    assert asyncio.run(hub.forgot(hub.ForgotIn(email=account["email"], channel="whatsapp"), tasks, request)) == response
    issue.assert_not_awaited()

    tenants.find_one.return_value = {"_id": tid, "phone_user_id": str(uid)}
    allow.return_value = True
    issue.reset_mock()
    email_send = AsyncMock()
    monkeypatch.setattr(hub, "send_password_reset_email", email_send)
    email_tasks = hub.BackgroundTasks()
    assert asyncio.run(hub.forgot(hub.ForgotIn(email=account["email"], channel="email"), email_tasks, request)) == response
    issue.assert_awaited_once_with(str(uid), account["email"], "restaurant")
    assert len(email_tasks.tasks) == 1
    assert email_tasks.tasks[0].func is email_send
    assert email_tasks.tasks[0].args[0] == account["email"]
    assert not tasks.tasks
    allow.return_value = False
    issue.reset_mock()
    assert asyncio.run(hub.forgot(hub.ForgotIn(email=account["email"], channel="whatsapp"), tasks, request)) == response
    issue.assert_not_awaited()


def test_recovery_ip_ignores_untrusted_forwarding_and_resolves_trusted_chain(hub, monkeypatch):
    request = SimpleNamespace(client=SimpleNamespace(host="192.0.2.5"),
                              headers={"x-forwarded-for": "198.51.100.5, 192.0.2.9"})
    monkeypatch.delenv("RECOVERY_TRUSTED_PROXY_CIDRS", raising=False)
    assert hub._recovery_client_ip(request) == "192.0.2.5"
    monkeypatch.setenv("RECOVERY_TRUSTED_PROXY_CIDRS", "192.0.2.0/24")
    assert hub._recovery_client_ip(request) == "198.51.100.5"


def test_invalid_status_never_changes_mobile_phone(hub, monkeypatch):
    users = SimpleNamespace(update_one=AsyncMock())
    tenants = SimpleNamespace(update_one=AsyncMock())
    monkeypatch.setattr(hub, "db", SimpleNamespace(tenant_users=users, tenants=tenants))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(hub.patch_tenant(str(ObjectId()), hub.TenantPatch(mobile_phone="11912345678", status="bad"),
                                     {"_id": "actor", "role": "super_admin"}))
    assert exc.value.status_code == 400
    users.update_one.assert_not_awaited()
    tenants.update_one.assert_not_awaited()


def test_whatsapp_reset_logs_only_safe_delivery_metadata(hub, monkeypatch, caplog):
    caplog.set_level("INFO", logger="dacot-hub")
    monkeypatch.setenv("WHATSAPP_SERVICE_URL", "https://whatsapp.example.test")
    monkeypatch.setenv("WHATSAPP_SERVICE_SECRET", "synthetic-service-secret-not-logged")
    send = AsyncMock(return_value=hub.DeliveryResult.ACCEPTED)
    monkeypatch.setattr(hub, "WhatsAppDeliveryProvider", lambda **_: SimpleNamespace(send=send))
    raw_token = "synthetic-reset-token"
    result = asyncio.run(hub._send_whatsapp_reset(
        "+5511912345678", raw_token, "first_access", tenant_id="tenant-safe-id"))
    assert result.value == "accepted"
    assert send.await_args.kwargs["number"] == "+5511912345678"
    assert send.await_args.kwargs["token"] == raw_token
    assert send.await_args.kwargs["purpose"] == "first_access"
    assert "whatsapp_delivery_result" in caplog.text
    assert "tenant-safe-id" in caplog.text
    assert raw_token not in caplog.text
    assert "11912345678" not in caplog.text
    assert "synthetic-service-secret-not-logged" not in caplog.text
