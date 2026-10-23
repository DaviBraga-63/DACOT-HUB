from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = ROOT_DIR.parent
FRONTEND_BUILD_DIR = PROJECT_DIR / "frontend" / "build"
load_dotenv(ROOT_DIR / ".env")

import os
import asyncio
import logging
import re
import secrets
import hashlib
import ipaddress
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Annotated, Any
from urllib.parse import urlparse

from handoff_policy import validate_handoff_configuration, validate_launch_url, orders_module_key
from orders_launch_urls import ORDERS_LAUNCH_URL_TEMPLATE, migrate_legacy_orders_launch_urls
from orders_user_grants import ORDERS_MODULE_KEY, bootstrap_orders_user_grants
from whatsapp_numbers import normalize_brazilian_number
from whatsapp_delivery import WhatsAppDeliveryProvider
from email_delivery import (
    send_orders_first_access_email as _send_orders_first_access_email,
    send_password_reset_email as _send_password_reset_email,
)
from auth_sessions import (
    BROWSER_COOKIE_NAME, TAB_SESSION_HEADER, create_session, ensure_indexes,
    find_session, new_browser_binding, refresh_session, revoke_session,
    revoke_user_sessions, valid_tab_session_id,
)

import bcrypt
import jwt
import httpx
from bson import ObjectId
from fastapi import FastAPI, APIRouter, HTTPException, Depends, Request, Response, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError
from pydantic import BaseModel, Field, EmailStr, BeforeValidator, ConfigDict

# ─── Setup ─────────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("dacot-hub")


class _ResetAccessLogFilter(logging.Filter):
    def filter(self, record):
        # Uvicorn access records carry the request target as the third argument.
        if isinstance(record.args, tuple) and len(record.args) >= 3:
            args = list(record.args)
            target = args[2]
            if isinstance(target, str) and target.split("?", 1)[0] == "/reset-password":
                args[2] = "/reset-password"
                record.args = tuple(args)
        return True


logging.getLogger("uvicorn.access").addFilter(_ResetAccessLogFilter())

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
# The application cannot operate without MongoDB.  Bound initial server
# selection so an unreachable database fails deployment promptly instead of
# keeping Uvicorn in its startup phase until the platform port scan expires.
MONGO_STARTUP_TIMEOUT_SECONDS = 15
client = AsyncIOMotorClient(
    MONGO_URL,
    serverSelectionTimeoutMS=MONGO_STARTUP_TIMEOUT_SECONDS * 1000,
    connectTimeoutMS=MONGO_STARTUP_TIMEOUT_SECONDS * 1000,
)
db = client[DB_NAME]

JWT_ALGORITHM = "HS256"
JWT_SECRET = os.environ["JWT_SECRET"]
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:3000")
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
EMAIL_FROM_ADDRESS = os.environ.get("EMAIL_FROM_ADDRESS", "")
EMAIL_FROM_NAME = os.environ.get("EMAIL_FROM_NAME") or "DACOT"
ORDERS_FRONTEND_URL = os.environ.get("ORDERS_FRONTEND_URL", "")

# ─── Module handoff (integration with external modules) ────────────────────────
HANDOFF_JWT_SECRET = os.environ.get("HANDOFF_JWT_SECRET", "")
HANDOFF_ISSUER = os.environ.get("HANDOFF_ISSUER", "dacot-hub")
HANDOFF_VERSION = 1
HANDOFF_MAX_TTL_SECONDS = 60
HANDOFF_AUDIENCE = {"orders": "dacot-orders", "kitchen": "dacot-kitchen"}
ORDERS_ANALYTICS_AUDIENCE = "dacot-orders-analytics"
ORDERS_ANALYTICS_SCOPE = "analytics.revenue"
MODULE_ACCESS_KEYS = {
    "orders": orders_module_key(),
    "kitchen": os.environ.get("KITCHEN_MODULE_KEY", ""),
}
VALID_HANDOFF_ROLES = {"admin", "manager", "waiter", "kitchen"}
HUB_ADMIN_ROLES = {"super_admin", "admin"}

app = FastAPI(title="DACOT Hub API")
api_router = APIRouter(prefix="/api")

@app.middleware("http")
async def protect_reset_response(request: Request, call_next):
    response = await call_next(request)
    if request.url.path in {"/reset-password", "/api/auth/reset-password"}:
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
    return response

# ─── Types & Base Model ────────────────────────────────────────────────────────
def _validate_object_id(v: Any) -> str:
    if isinstance(v, ObjectId):
        return str(v)
    if isinstance(v, str) and ObjectId.is_valid(v):
        return v
    raise ValueError("Invalid ObjectId")

PyObjectId = Annotated[str, BeforeValidator(_validate_object_id)]


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _orders_backend_url() -> str:
    """Return the exact service origin used only for Hub → Pedidos calls."""
    value = os.environ.get("ORDERS_BACKEND_URL", "").strip().rstrip("/")
    parsed = urlparse(value)
    is_local_development = (
        os.environ.get("APP_ENV", "").strip().lower() == "development"
        and parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    )
    if (not parsed.hostname or parsed.username or parsed.password or parsed.path not in ("", "/")
            or parsed.query or parsed.fragment or "\\" in value
            or (parsed.scheme != "https" and not is_local_development)):
        raise HTTPException(503, "Integração com Pedidos indisponível")
    return value


def _orders_frontend_url() -> str:
    value = ORDERS_FRONTEND_URL.strip().rstrip("/")
    parsed = urlparse(value)
    is_local_development = (
        os.environ.get("APP_ENV", "").strip().lower() == "development"
        and parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    )
    if (not parsed.hostname or parsed.username or parsed.password or parsed.path not in ("", "/")
            or parsed.query or parsed.fragment or "\\" in value
            or (parsed.scheme != "https" and not is_local_development)):
        raise HTTPException(503, "URL do frontend Pedidos não configurada")
    return value


def iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


# ─── Password / JWT ────────────────────────────────────────────────────────────
def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


async def _email_in_use(email: str, *, exclude_collection: Optional[str] = None,
                        exclude_id: Optional[ObjectId] = None) -> bool:
    """Cross-collection uniqueness: hub_users and tenant_users each already
    enforce their own unique email index, but nothing stopped the same email
    existing in both. Login resolves hub_users first, so such a collision
    would silently shadow the tenant_user, making it permanently unreachable.
    Called from every create/edit path in both collections."""
    hub_query: dict = {"email": email}
    tenant_query: dict = {"email": email}
    if exclude_collection == "hub_users" and exclude_id is not None:
        hub_query["_id"] = {"$ne": exclude_id}
    if exclude_collection == "tenant_users" and exclude_id is not None:
        tenant_query["_id"] = {"$ne": exclude_id}
    if await db.hub_users.find_one(hub_query):
        return True
    if await db.tenant_users.find_one(tenant_query):
        return True
    return False


def _set_browser_binding_cookie(response: Response, binding: str) -> None:
    """Cookie HttpOnly shared by browser tabs; it is not auth on its own."""
    response.set_cookie(BROWSER_COOKIE_NAME, binding, httponly=True, secure=True,
                        samesite="none", path="/")


def _expire_legacy_auth_cookies(response: Response) -> None:
    """JWT cookies are migration cleanup only and are never consulted for auth."""
    response.delete_cookie("access_token", path="/", secure=True, httponly=True, samesite="none")
    response.delete_cookie("refresh_token", path="/", secure=True, httponly=True, samesite="none")


def _security_version(doc: dict, field: str) -> Optional[int]:
    # A missing counter is the documented legacy version. An explicit null or
    # malformed counter is not evidence that version zero was never revoked.
    value = doc.get(field, 0)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _version_increment_update(field: str, values: dict) -> list:
    """Atomically increment valid/missing counters; preserve invalid counters fail-closed."""
    ref = f"${field}"
    increment = {"$switch": {"branches": [
        {"case": {"$eq": [{"$type": ref}, "missing"]}, "then": 1},
        {"case": {"$in": [{"$type": ref}, ["int", "long"]]},
         "then": {"$cond": [{"$gte": [ref, 0]}, {"$add": [ref, 1]}, ref]}},
    ], "default": ref}}
    return [{"$set": {**{key: {"$literal": value} for key, value in values.items()},
                       field: increment}}]


async def _user_for_session(session: dict) -> dict:
    """Re-resolve authority from Mongo; session fields never grant a role."""
    ut = session.get("user_type")
    if ut not in {"staff", "restaurant"} or not ObjectId.is_valid(session.get("user_id", "")):
        raise HTTPException(401, "Sessão inválida")
    coll = db.hub_users if ut == "staff" else db.tenant_users
    user = await coll.find_one({"_id": ObjectId(session["user_id"])})
    if not user:
        raise HTTPException(401, "Usuário não encontrado")
    if ut == "staff" and (not user.get("active", True) or user.get("deleted_at")):
        raise HTTPException(401, "Usuário não encontrado")
    if ut == "restaurant" and (user.get("deleted_at") or user.get("status", "active") != "active" or user.get("password_reset_required")):
        raise HTTPException(401, "Usuário não encontrado")
    if ut == "restaurant":
        tenant = await db.tenants.find_one({"_id": ObjectId(user["tenant_id"])})
        if not tenant or tenant.get("deleted_at"):
            raise HTTPException(401, "Usuário não encontrado")
    user_version = _security_version(user, "token_version")
    session_version = _security_version(session, "user_token_version")
    if user_version is None or session_version is None or session_version != user_version:
        raise HTTPException(401, "Sessão expirada")
    user["_id"] = str(user["_id"])
    user.pop("password_hash", None)
    user["user_type"] = ut
    return user


async def _session_from_request(request: Request, *, require_access: bool) -> Optional[dict]:
    return await find_session(
        db,
        browser_binding=request.cookies.get(BROWSER_COOKIE_NAME),
        tab_session_id=request.headers.get(TAB_SESSION_HEADER),
        require_access=require_access,
    )


async def get_current_user(request: Request) -> dict:
    # Deliberately no JWT-cookie or Authorization bearer fallback: browser
    # authentication is fail-closed on the binding + per-tab session record.
    session = await _session_from_request(request, require_access=True)
    if not session:
        raise HTTPException(401, "Não autenticado")
    return await _user_for_session(session)


# ─── Authorization dependencies (two role scopes, never collapsed) ─────────────
async def get_staff_user(user: dict = Depends(get_current_user)) -> dict:
    """DACOT team only (super_admin/admin/viewer) — read access to the admin area."""
    if user.get("user_type") != "staff":
        raise HTTPException(403, "Acesso restrito à equipe DACOT")
    return user


async def get_staff_write(user: dict = Depends(get_staff_user)) -> dict:
    """DACOT team write access — viewer cannot modify anything."""
    if user.get("role") not in HUB_ADMIN_ROLES:
        raise HTTPException(403, "Permissão insuficiente para alterar dados")
    return user


async def get_super_admin(user: dict = Depends(get_staff_user)) -> dict:
    if user.get("role") != "super_admin":
        raise HTTPException(403, "Permissão restrita a super administradores")
    return user


async def get_restaurant_user(user: dict = Depends(get_current_user)) -> dict:
    """Restaurant client — tenant_id always comes from the authenticated identity.
    Also gates on the tenant being operational: a suspended/inactive tenant loses
    all portal and handoff access immediately, even mid-session (this is checked
    on every request here, not just at login). The resolved tenant is attached
    so callers (portal_context, portal_launch_token) don't re-query it."""
    if user.get("user_type") != "restaurant" or not user.get("tenant_id"):
        raise HTTPException(403, "Acesso restrito a usuários de restaurante")
    tenant = await db.tenants.find_one({"_id": ObjectId(user["tenant_id"])})
    if not tenant or not _tenant_operational(tenant):
        raise HTTPException(403, "Restaurante suspenso ou inativo")
    user["tenant"] = tenant
    return user


async def get_restaurant_admin(user: dict = Depends(get_restaurant_user)) -> dict:
    """Tenant-scoped administration; never grants access to DACOT staff APIs."""
    if user.get("role") != "admin":
        raise HTTPException(403, "Permissão restrita ao administrador do restaurante")
    return user


# ─── Brute-force helpers ───────────────────────────────────────────────────────
async def _check_lockout(ip: str, email: str) -> None:
    ident = f"{ip}:{email}"
    since = now_utc() - timedelta(minutes=15)
    cnt = await db.login_attempts.count_documents({
        "identifier": ident, "created_at": {"$gt": since.isoformat()}, "success": False
    })
    if cnt >= 5:
        raise HTTPException(429, "Muitas tentativas de login. Tente novamente em 15 minutos.")


async def _record_attempt(ip: str, email: str, success: bool) -> None:
    await db.login_attempts.insert_one({
        "identifier": f"{ip}:{email}", "email": email, "success": success,
        "created_at": now_utc().isoformat(),
    })


# ─── Email (reset) ─────────────────────────────────────────────────────────────
async def send_password_reset_email(to_email: str, token: str, validity_hours: int = 24) -> bool:
    return await _send_password_reset_email(
        to_email,
        token,
        frontend_url=FRONTEND_URL,
        resend_api_key=RESEND_API_KEY,
        email_from_address=EMAIL_FROM_ADDRESS,
        email_from_name=EMAIL_FROM_NAME, validity_hours=validity_hours,
    )


async def send_orders_first_access_email(to_email: str, token: str) -> bool:
    if os.environ.get("APP_ENV") == "development" and os.environ.get("DACOT_LOCAL_INTEGRATION") == "1":
        return True
    return await _send_orders_first_access_email(
        to_email, token, orders_frontend_url=_orders_frontend_url(),
        resend_api_key=RESEND_API_KEY, email_from_address=EMAIL_FROM_ADDRESS,
        email_from_name=EMAIL_FROM_NAME,
    )


# ─── Auth Models ───────────────────────────────────────────────────────────────
class LoginIn(BaseModel):
    email: EmailStr
    password: str

class ForgotIn(BaseModel):
    email: EmailStr
    channel: str = "email"

class ResetIn(BaseModel):
    token: str
    password: str = Field(min_length=6)


async def _issue_password_reset(user_id: str, email: str, user_type: str, *, first_access: bool = False,
                                whatsapp_version: Optional[str] = None) -> str:
    """Create the existing one-time reset credential without exposing it."""
    raw = secrets.token_urlsafe(32)
    generation = secrets.token_urlsafe(32)
    coll = db.tenant_users if user_type == "restaurant" else db.hub_users
    query = {"_id": ObjectId(user_id), "deleted_at": None}
    if whatsapp_version is not None:
        query["whatsapp_binding_version"] = whatsapp_version
        query["status"] = "active"
    changed = await coll.update_one(
        query,
        {"$set": {"password_reset_generation": generation}},
    )
    if changed.matched_count != 1:
        raise HTTPException(400, "Não foi possível preparar a redefinição")
    await db.password_reset_tokens.insert_one({
        "token_hash": hashlib.sha256(raw.encode()).hexdigest(),
        "user_id": user_id, "email": email, "user_type": user_type,
        "generation": generation,
        "whatsapp_binding_version": whatsapp_version,
        "used": False, "expires_at": now_utc() + timedelta(days=30 if first_access else 1),
        "created_at": now_utc(),
    })
    return raw


async def _send_whatsapp_reset(number: str, token: str, purpose: str):
    provider = WhatsAppDeliveryProvider(
        service_url=os.environ.get("WHATSAPP_SERVICE_URL", ""),
        service_key=os.environ.get("WHATSAPP_SERVICE_SECRET", ""),
        frontend_url=FRONTEND_URL,
        ca_file=os.environ.get("WHATSAPP_SERVICE_CA_FILE") or None,
        service_transport=os.environ.get("WHATSAPP_SERVICE_TRANSPORT", "https"),
    )
    result = await provider.send(number=number, token=token, purpose=purpose,
                                 request_id=hashlib.sha256(token.encode()).hexdigest())
    if result.value != "accepted":
        logger.warning("whatsapp_delivery_unavailable purpose=%s", purpose)
    return result


# ─── Auth endpoints ────────────────────────────────────────────────────────────
def _client_ip(request: Request) -> str:
    # Login and recovery must apply the same explicit proxy trust policy.
    return _recovery_client_ip(request)


@api_router.post("/auth/login")
async def login(payload: LoginIn, request: Request, response: Response):
    email = payload.email.lower()
    ip = _client_ip(request)
    await _check_lockout(ip, email)
    # Single login for both populations: staff first, then restaurant users.
    user = await db.hub_users.find_one({"email": email})
    ut = "staff"
    if not user:
        user = await db.tenant_users.find_one({"email": email})
        ut = "restaurant"
    valid = bool(user) and bool(user.get("password_hash")) and verify_password(payload.password, user["password_hash"])
    if valid and _security_version(user, "token_version") is None:
        valid = False
    if valid and ut == "staff" and (not user.get("active", True) or user.get("deleted_at")):
        valid = False
    if valid and ut == "restaurant" and (user.get("deleted_at") or user.get("status", "active") != "active" or user.get("password_reset_required")):
        valid = False
    if valid and ut == "restaurant":
        tenant = await db.tenants.find_one({"_id": ObjectId(user["tenant_id"])})
        if not tenant or tenant.get("deleted_at"):
            valid = False
    tenant = None
    if valid and ut == "restaurant":
        tenant = await db.tenants.find_one({"_id": ObjectId(user["tenant_id"])}) if user.get("tenant_id") else None
        # A restaurant account tied to a suspended/inactive tenant is treated
        # the same as an inactive user — no session is issued.
        if not tenant or not _tenant_operational(tenant):
            valid = False
    if not valid:
        await _record_attempt(ip, email, False)
        raise HTTPException(401, "E-mail ou senha inválidos")
    coll = db.hub_users if ut == "staff" else db.tenant_users
    await db.login_attempts.delete_many({"email": email})
    await coll.update_one({"_id": user["_id"]}, {"$set": {"last_login_at": now_utc().isoformat()}})
    uid = str(user["_id"])
    ver = _security_version(user, "token_version")
    tab_session_id = request.headers.get(TAB_SESSION_HEADER)
    if not tab_session_id:
        raise HTTPException(400, "Identificador da aba ausente")
    if not valid_tab_session_id(tab_session_id):
        raise HTTPException(400, "Identificador da aba inválido")
    browser_binding = request.cookies.get(BROWSER_COOKIE_NAME)
    if not browser_binding:
        browser_binding = new_browser_binding()
        _set_browser_binding_cookie(response, browser_binding)
    await create_session(
        db, browser_binding=browser_binding, tab_session_id=tab_session_id,
        user_id=uid, user_type=ut, user_token_version=ver,
    )
    # Existing browser JWTs are deliberately not a fallback after migration.
    _expire_legacy_auth_cookies(response)
    await log_activity(actor_id=uid, actor_name=user.get("name", email),
                       action="hub_user.login" if ut == "staff" else "restaurant_user.login",
                       target_type=ut, target_id=uid,
                       tenant_id=user.get("tenant_id") if ut == "restaurant" else None)
    out = {"id": uid, "email": email, "name": user.get("name"),
           "role": user.get("role", "admin" if ut == "staff" else "waiter"),
           "user_type": ut}
    if ut == "restaurant":
        out["tenant_id"] = user.get("tenant_id")
        out["tenant_name"] = tenant["name"] if tenant else None
    return out


@api_router.post("/auth/logout")
async def logout(request: Request, response: Response):
    await revoke_session(
        db,
        browser_binding=request.cookies.get(BROWSER_COOKIE_NAME),
        tab_session_id=request.headers.get(TAB_SESSION_HEADER),
        reason="logout",
    )
    # Keep the browser binding: other tabs rely on it together with their own
    # opaque identifiers. Only obsolete, non-authoritative JWT cookies go away.
    _expire_legacy_auth_cookies(response)
    return {"ok": True}


@api_router.get("/auth/me")
async def me(user: dict = Depends(get_current_user)):
    out = {"id": user["_id"], "email": user["email"], "name": user.get("name"),
           "role": user.get("role", "admin" if user["user_type"] == "staff" else "waiter"),
           "user_type": user["user_type"]}
    if user["user_type"] == "restaurant":
        out["tenant_id"] = user.get("tenant_id")
        tenant = await db.tenants.find_one({"_id": ObjectId(user["tenant_id"])}) if user.get("tenant_id") else None
        out["tenant_name"] = tenant["name"] if tenant else None
    return out


@api_router.post("/auth/refresh")
async def refresh(request: Request, response: Response):
    session = await refresh_session(
        db,
        browser_binding=request.cookies.get(BROWSER_COOKIE_NAME),
        tab_session_id=request.headers.get(TAB_SESSION_HEADER),
    )
    if not session:
        raise HTTPException(401, "Sessão expirada")
    await _user_for_session(session)
    return {"ok": True}


GENERIC_RESET_RESPONSE = {"message": "Se este e-mail estiver cadastrado, um link de redefinição foi enviado."}


def _recovery_client_ip(request: Request) -> str:
    """Only trust forwarding data received directly from explicitly trusted proxies.

    Run Uvicorn with --no-proxy-headers so request.client remains the direct peer.
    """
    try:
        peer = ipaddress.ip_address(request.client.host)
        networks = [ipaddress.ip_network(value.strip()) for value in
                    os.environ.get("RECOVERY_TRUSTED_PROXY_CIDRS", "").split(",") if value.strip()]
        if not any(peer in network for network in networks):
            return peer.compressed
        hops = [ipaddress.ip_address(value.strip()) for value in request.headers.get("x-forwarded-for", "").split(",") if value.strip()]
        if len(hops) > 20:
            return "unknown"
        for hop in reversed(hops):
            if not any(hop in network for network in networks):
                return hop.compressed
        return peer.compressed
    except (ValueError, AttributeError):
        return "unknown"


async def _allow_recovery_request(email: str, ip: str) -> bool:
    """Shared, atomic counters and a sliding account cooldown; fail closed."""
    now = now_utc()
    bucket = int(now.timestamp()) // 900
    try:
        for scope, identity, limit in (("global", "all", 500), ("origin", ip, 20)):
            key = hashlib.sha256(f"{scope}:{identity}:{bucket}".encode()).hexdigest()
            doc = await db.password_reset_requests.find_one_and_update(
                {"_id": key}, {"$inc": {"count": 1}, "$setOnInsert": {"created_at": now}},
                upsert=True, return_document=ReturnDocument.AFTER,
            )
            if doc["count"] > limit:
                return False
        key = hashlib.sha256(f"account:{email}".encode()).hexdigest()
        try:
            await db.password_reset_cooldowns.update_one(
                {"_id": key, "$or": [{"last_allowed": {"$lte": now - timedelta(minutes=15)}},
                                       {"last_allowed": {"$exists": False}}]},
                {"$set": {"last_allowed": now}}, upsert=True,
            )
        except DuplicateKeyError:
            return False
        return True
    except PyMongoError:
        logger.warning("password_recovery_rate_limiter_unavailable")
        return False


@api_router.post("/auth/forgot-password")
async def forgot(payload: ForgotIn, background_tasks: BackgroundTasks, request: Request):
    if payload.channel not in {"email", "whatsapp"}:
        raise HTTPException(400, "Canal inválido")
    email = payload.email.lower()
    if not await _allow_recovery_request(email, _recovery_client_ip(request)):
        return GENERIC_RESET_RESPONSE
    user = await db.hub_users.find_one({"email": email})
    ut = "staff"
    if not user:
        user = await db.tenant_users.find_one({"email": email})
        ut = "restaurant"
    if not user or user.get("deleted_at"):
        return GENERIC_RESET_RESPONSE
    if ut == "restaurant":
        tenant = await db.tenants.find_one({"_id": ObjectId(user["tenant_id"])})
        if not tenant or tenant.get("deleted_at"):
            return GENERIC_RESET_RESPONSE
    if payload.channel == "whatsapp":
        if (ut != "restaurant" or user.get("status", "active") != "active"
                or tenant.get("whatsapp_user_id") != str(user["_id"])
                or not user.get("whatsapp_number") or not user.get("whatsapp_binding_version")):
            return GENERIC_RESET_RESPONSE
        try:
            raw = await _issue_password_reset(str(user["_id"]), email, ut,
                                              whatsapp_version=user["whatsapp_binding_version"])
        except HTTPException:
            return GENERIC_RESET_RESPONSE
        background_tasks.add_task(_send_whatsapp_reset, user["whatsapp_number"], raw, "recovery")
    else:
        raw = await _issue_password_reset(str(user["_id"]), email, ut)
        background_tasks.add_task(send_password_reset_email, user["email"], raw)
    return GENERIC_RESET_RESPONSE


@api_router.post("/auth/reset-password")
async def reset(payload: ResetIn):
    h = hashlib.sha256(payload.token.encode()).hexdigest()
    doc = await db.password_reset_tokens.find_one_and_update(
        {"token_hash": h, "used": False, "expires_at": {"$gt": now_utc()}},
        {"$set": {"used": True}},
    )
    if not doc:
        raise HTTPException(400, "Token inválido ou expirado")
    email = doc["email"]
    user_type = doc.get("user_type")
    coll = db.tenant_users if user_type == "restaurant" else db.hub_users
    if user_type == "restaurant":
        restaurant_user = await db.tenant_users.find_one({"_id": ObjectId(doc["user_id"])})
        tenant = await db.tenants.find_one({"_id": ObjectId(restaurant_user["tenant_id"])}) if restaurant_user else None
        if not restaurant_user or restaurant_user.get("deleted_at") or not tenant or tenant.get("deleted_at"):
            raise HTTPException(400, "Token inválido ou expirado")
    user_query = {"_id": ObjectId(doc["user_id"]), "deleted_at": None}
    # Legacy credentials predate generations. They remain valid only until a
    # newer credential has been issued for that account.
    user_query["password_reset_generation"] = doc.get("generation")
    if doc.get("whatsapp_binding_version") is not None:
        user_query["whatsapp_binding_version"] = doc["whatsapp_binding_version"]
        user_query["status"] = "active"
    changed = await coll.update_one(
        user_query,
        _version_increment_update("token_version", {
            "password_hash": hash_password(payload.password), "password_reset_required": False,
            "password_reset_generation": secrets.token_urlsafe(32),
        }),
    )
    if changed.matched_count != 1:
        raise HTTPException(400, "Token inválido ou expirado")
    await revoke_user_sessions(
        db, user_id=doc["user_id"], user_type=doc.get("user_type", "staff"), reason="password_reset"
    )
    await db.login_attempts.delete_many({"email": email})
    return {"ok": True}


# ─── Activity log helper ───────────────────────────────────────────────────────
async def log_activity(*, actor_id: str, actor_name: str, action: str,
                       target_type: str, target_id: Optional[str] = None,
                       tenant_id: Optional[str] = None, metadata: Optional[dict] = None):
    await db.activity_log.insert_one({
        "actor_id": actor_id, "actor_name": actor_name, "action": action,
        "target_type": target_type, "target_id": target_id,
        "tenant_id": tenant_id, "metadata": metadata or {},
        "created_at": now_utc().isoformat(),
    })


# ─── Tenant / Module models ────────────────────────────────────────────────────
class TenantIn(BaseModel):
    name: str
    owner_name: str
    email: EmailStr
    phone: Optional[str] = ""
    whatsapp_phone: Optional[str] = ""
    status: str = "trial"
    address: Optional[str] = ""
    notes: Optional[str] = ""


class TenantOnboardingIn(TenantIn):
    create_hub_access: bool = False
    access_name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    access_email: Optional[EmailStr] = None
    access_channel: str = "email"

class TenantPatch(BaseModel):
    name: Optional[str] = None
    owner_name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    whatsapp_phone: Optional[str] = None
    status: Optional[str] = None
    address: Optional[str] = None
    notes: Optional[str] = None


class WhatsAppBindingIn(BaseModel):
    user_id: str
    phone: str


VALID_STATUS = {"active", "trial", "suspended", "inactive"}
# A tenant is operational (can log in, use the portal, or receive a handoff
# into an external module) only in "active"/"trial". "suspended"/"inactive"
# keep all Hub administration working (staff can still view/edit/toggle
# modules), but block anything that opens the tenant's own operational side.
TENANT_OPERATIONAL_STATUSES = {"active", "trial"}


def _tenant_operational(tenant: dict) -> bool:
    return not tenant.get("deleted_at") and tenant.get("status", "trial") in TENANT_OPERATIONAL_STATUSES


def _slug(name: str) -> str:
    import re, unicodedata
    n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    n = re.sub(r"[^a-zA-Z0-9]+", "-", n).strip("-").lower()
    return n or "tenant"


def _tenant_out(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "name": doc["name"],
        "slug": doc.get("slug", ""),
        "owner_name": doc.get("owner_name", ""),
        "email": doc.get("email", ""),
        "phone": doc.get("phone", ""),
        "whatsapp_phone": doc.get("whatsapp_phone", ""),
        "whatsapp_user_id": doc.get("whatsapp_user_id"),
        "status": doc.get("status", "trial"),
        "address": doc.get("address", ""),
        "notes": doc.get("notes", ""),
        "created_at": doc.get("created_at"),
    }


def _new_tenant_doc(payload: TenantIn) -> dict:
    if payload.status not in VALID_STATUS:
        raise HTTPException(400, "Status inválido")
    try:
        whatsapp_phone = normalize_brazilian_number(payload.whatsapp_phone) if payload.whatsapp_phone else ""
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    return {
        "name": payload.name.strip(),
        "slug": _slug(payload.name),
        "owner_name": payload.owner_name.strip(),
        "email": payload.email.lower(),
        "phone": payload.phone or "",
        "whatsapp_phone": whatsapp_phone,
        "status": payload.status,
        "address": payload.address or "",
        "notes": payload.notes or "",
        "created_at": now_utc().isoformat(),
        "updated_at": now_utc().isoformat(),
    }


# ─── Tenants ───────────────────────────────────────────────────────────────────
@api_router.get("/hub/tenants")
async def list_tenants(status: Optional[str] = None, q: Optional[str] = None,
                       _u: dict = Depends(get_staff_user)):
    query: dict = {"deleted_at": None}
    if status and status != "all":
        query["status"] = status
    if q:
        query["$or"] = [{"name": {"$regex": q, "$options": "i"}},
                        {"owner_name": {"$regex": q, "$options": "i"}},
                        {"email": {"$regex": q, "$options": "i"}}]
    docs = await db.tenants.find(query).sort("created_at", -1).to_list(500)
    out = []
    for d in docs:
        base = _tenant_out(d)
        tid = str(d["_id"])
        active_mods = await db.tenant_modules.count_documents({"tenant_id": tid, "active": True})
        users = await db.tenant_users.count_documents({"tenant_id": tid, "deleted_at": None})
        base["active_modules"] = active_mods
        base["users_count"] = users
        out.append(base)
    return out


@api_router.post("/hub/tenants")
async def create_tenant(payload: TenantIn, user: dict = Depends(get_super_admin)):
    doc = _new_tenant_doc(payload)
    if doc["whatsapp_phone"]:
        doc["whatsapp_audit"] = [{"action": "set", "actor_id": user["_id"], "at": now_utc().isoformat()}]
    res = await db.tenants.insert_one(doc)
    tid = str(res.inserted_id)
    await log_activity(actor_id=user["_id"], actor_name=user.get("name", user["email"]),
                       action="tenant.created", target_type="tenant", target_id=tid,
                       tenant_id=tid, metadata={"name": doc["name"]})
    doc["_id"] = res.inserted_id
    return {**_tenant_out(doc), "active_modules": 0, "users_count": 0}


@api_router.post("/hub/tenants/onboard")
async def onboard_tenant(payload: TenantOnboardingIn, background_tasks: BackgroundTasks,
                         user: dict = Depends(get_super_admin)):
    """Create a tenant and, when requested, its first manager access safely.

    Mongo deployments are not assumed to support transactions. All validation
    that does not require persistence happens first; if the new user cannot be
    created, only the tenant inserted by this request is compensated.
    """
    doc = _new_tenant_doc(payload)
    if payload.access_channel not in {"email", "whatsapp"}:
        raise HTTPException(400, "Canal inválido")
    if payload.create_hub_access and payload.access_channel == "whatsapp" and not doc["whatsapp_phone"]:
        raise HTTPException(400, "WhatsApp do responsável é obrigatório")
    if doc["whatsapp_phone"]:
        doc["whatsapp_audit"] = [{"action": "set", "actor_id": user["_id"], "at": now_utc().isoformat()}]
    access_name = (payload.access_name or payload.owner_name).strip()
    access_email = (payload.access_email or payload.email).lower()
    if payload.create_hub_access:
        if not access_name:
            raise HTTPException(400, "Nome do responsável é obrigatório")
        if await _email_in_use(access_email):
            raise HTTPException(409, "Já existe um usuário com este e-mail")

    inserted = await db.tenants.insert_one(doc)
    tid = str(inserted.inserted_id)
    doc["_id"] = inserted.inserted_id
    created_user_id: Optional[str] = None
    raw_reset: Optional[str] = None
    try:
        access_created = False
        if payload.create_hub_access:
            created_user_id = await _create_initial_tenant_manager(tid, access_name, access_email)
            version = None
            if doc["whatsapp_phone"]:
                version = secrets.token_urlsafe(32)
                binding = await db.tenant_users.update_one(
                    {"_id": ObjectId(created_user_id), "tenant_id": tid, "deleted_at": None},
                    {"$set": {"whatsapp_number": doc["whatsapp_phone"], "whatsapp_binding_version": version},
                     "$push": {"whatsapp_audit": {"actor_id": user["_id"], "at": now_utc().isoformat()}}},
                )
                if binding.matched_count != 1:
                    raise HTTPException(409, "Responsável não está disponível")
                await db.tenants.update_one({"_id": inserted.inserted_id}, {"$set": {"whatsapp_user_id": created_user_id}})
                doc["whatsapp_user_id"] = created_user_id
            raw_reset = await _issue_password_reset(created_user_id, access_email, "restaurant", first_access=True,
                                                     whatsapp_version=version if payload.access_channel == "whatsapp" else None)
            access_created = True
        await log_activity(
            actor_id=user["_id"], actor_name=user.get("name", user["email"]),
            action="tenant.onboarded", target_type="tenant", target_id=tid, tenant_id=tid,
            metadata={"name": doc["name"], "initial_access_created": access_created,
                      "initial_access_user_id": created_user_id, "initial_access_role": "manager" if access_created else None},
        )
    except Exception:
        # This ID was created in this request and has no other dependencies yet.
        if created_user_id:
            await db.password_reset_tokens.delete_many({"user_id": created_user_id, "used": False})
            await db.tenant_users.delete_one({"_id": ObjectId(created_user_id), "tenant_id": tid})
        await db.tenants.delete_one({"_id": inserted.inserted_id})
        raise
    invitation = None
    if raw_reset and payload.access_channel == "whatsapp":
        invitation = (await _send_whatsapp_reset(doc["whatsapp_phone"], raw_reset, "first_access")).value
    elif raw_reset:
        background_tasks.add_task(send_password_reset_email, access_email, raw_reset, 30 * 24)
        invitation = "queued"
    return {**_tenant_out(doc), "active_modules": 0, "users_count": 1 if payload.create_hub_access else 0,
            "initial_access_created": payload.create_hub_access,
            "invitation": invitation}


@api_router.get("/hub/tenants/{tid}")
async def get_tenant(tid: str, _u: dict = Depends(get_staff_user)):
    if not ObjectId.is_valid(tid):
        raise HTTPException(404, "Cliente não encontrado")
    d = await db.tenants.find_one({"_id": ObjectId(tid), "deleted_at": None})
    if not d:
        raise HTTPException(404, "Cliente não encontrado")
    if d.get("whatsapp_user_id") and ObjectId.is_valid(d["whatsapp_user_id"]):
        owner = await db.tenant_users.find_one({"_id": ObjectId(d["whatsapp_user_id"]), "tenant_id": tid, "deleted_at": None})
        d["whatsapp_phone"] = owner.get("whatsapp_number", "") if owner else ""
    base = _tenant_out(d)
    base["active_modules"] = await db.tenant_modules.count_documents({"tenant_id": tid, "active": True})
    base["users_count"] = await db.tenant_users.count_documents({"tenant_id": tid, "deleted_at": None})
    return base


@api_router.put("/hub/tenants/{tid}/whatsapp")
async def bind_whatsapp(tid: str, payload: WhatsAppBindingIn, user: dict = Depends(get_super_admin)):
    if not ObjectId.is_valid(tid) or not ObjectId.is_valid(payload.user_id):
        raise HTTPException(404, "Cliente ou usuário não encontrado")
    try:
        phone = normalize_brazilian_number(payload.phone)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    async def bind(session):
        owner = await db.tenant_users.find_one({"_id": ObjectId(payload.user_id), "tenant_id": tid,
                                                "deleted_at": None, "status": "active"}, session=session)
        if not owner:
            raise HTTPException(404, "Usuário ativo não encontrado neste restaurante")
        tenant = await db.tenants.find_one_and_update(
            {"_id": ObjectId(tid), "deleted_at": None,
             "$or": [{"whatsapp_user_id": None}, {"whatsapp_user_id": payload.user_id}]},
            {"$set": {"whatsapp_user_id": payload.user_id, "whatsapp_phone": phone}},
            return_document=ReturnDocument.AFTER, session=session,
        )
        if not tenant:
            raise HTTPException(409, "Outro responsável já está vinculado ao WhatsApp")
        result = await db.tenant_users.update_one(
            {"_id": ObjectId(payload.user_id), "tenant_id": tid, "deleted_at": None, "status": "active"},
            {"$set": {"whatsapp_number": phone, "whatsapp_binding_version": secrets.token_urlsafe(32)},
             "$push": {"whatsapp_audit": {"actor_id": user["_id"], "at": now_utc().isoformat(), "action": "set"}}},
            session=session,
        )
        if result.matched_count != 1:
            raise HTTPException(409, "Responsável não está mais disponível")
    await _whatsapp_transaction(bind)
    return {"ok": True}


async def _whatsapp_transaction(callback):
    """Fail closed if the MongoDB deployment cannot provide transactions."""
    try:
        async with await client.start_session() as session:
            return await session.with_transaction(callback)
    except PyMongoError:
        logger.warning("whatsapp_binding_transaction_unavailable")
        raise HTTPException(503, "Alteração de WhatsApp temporariamente indisponível") from None


@api_router.patch("/hub/tenants/{tid}")
async def patch_tenant(tid: str, payload: TenantPatch, user: dict = Depends(get_staff_write)):
    if not ObjectId.is_valid(tid):
        raise HTTPException(404, "Cliente não encontrado")
    update = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    if "email" in update:
        update["email"] = update["email"].lower()
    if "status" in update and update["status"] not in VALID_STATUS:
        raise HTTPException(400, "Status inválido")
    if "name" in update:
        update["slug"] = _slug(update["name"])
    phone_was_unbound = False
    if "whatsapp_phone" in update:
        if user.get("role") != "super_admin":
            raise HTTPException(403, "Somente super administradores podem alterar o WhatsApp")
        try:
            update["whatsapp_phone"] = normalize_brazilian_number(update["whatsapp_phone"]) if update["whatsapp_phone"] else ""
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
    async def update_documents(session=None):
        nonlocal phone_was_unbound
        options = {"session": session} if session is not None else {}
        tenant = await db.tenants.find_one({"_id": ObjectId(tid), "deleted_at": None}, **options) if "whatsapp_phone" in update else None
        if "whatsapp_phone" in update and not tenant:
            raise HTTPException(404, "Cliente não encontrado")
        if tenant:
            owner_id = tenant.get("whatsapp_user_id")
            phone_was_unbound = not owner_id
            if owner_id:
                if not ObjectId.is_valid(owner_id):
                    raise HTTPException(409, "Vínculo de WhatsApp inválido")
                event = {"actor_id": user["_id"], "at": now_utc().isoformat(), "action": "change"}
                changed = await db.tenant_users.update_one(
                    {"_id": ObjectId(owner_id), "tenant_id": tid, "deleted_at": None},
                    {"$set": {"whatsapp_number": update["whatsapp_phone"],
                              "whatsapp_binding_version": secrets.token_urlsafe(32)},
                     "$push": {"whatsapp_audit": event}}, **options,
                )
                if changed.matched_count != 1:
                    raise HTTPException(409, "Responsável vinculado não está disponível")
        tenant_query = {"_id": ObjectId(tid), "deleted_at": None}
        if phone_was_unbound:
            tenant_query["whatsapp_user_id"] = None
        r = await db.tenants.update_one(tenant_query, mutation, **options)
        if r.matched_count == 0:
            raise HTTPException(409 if phone_was_unbound else 404, "Cliente não encontrado ou vínculo alterado")

    update["updated_at"] = now_utc().isoformat()
    mutation = {"$set": update}
    if "status" in update:
        mutation = _version_increment_update("access_version", update)
    if "whatsapp_phone" in update:
        event = {"action": "set" if update["whatsapp_phone"] else "clear",
                 "actor_id": user["_id"], "at": now_utc().isoformat()}
        if isinstance(mutation, list):
            mutation.append({"$set": {"whatsapp_audit": {"$concatArrays": [
                {"$ifNull": ["$whatsapp_audit", []]}, {"$literal": [event]}]}}})
        else:
            mutation["$push"] = {"whatsapp_audit": event}
    if "whatsapp_phone" in update:
        await _whatsapp_transaction(update_documents)
    else:
        await update_documents()
    if "status" in update:
        await log_activity(actor_id=user["_id"], actor_name=user.get("name", user["email"]),
                           action="tenant.status_changed", target_type="tenant",
                           target_id=tid, tenant_id=tid, metadata={"status": update["status"]})
    d = await db.tenants.find_one({"_id": ObjectId(tid), "deleted_at": None})
    return _tenant_out(d)


@api_router.delete("/hub/tenants/{tid}")
async def delete_tenant(tid: str, user: dict = Depends(get_staff_write)):
    if not ObjectId.is_valid(tid):
        raise HTTPException(404, "Cliente não encontrado")
    oid = ObjectId(tid)
    tenant = await db.tenants.find_one({"_id": oid, "deleted_at": None})
    if not tenant:
        raise HTTPException(404, "Cliente não encontrado")
    now = now_utc().isoformat()
    result = await db.tenants.update_one(
        {"_id": oid, "deleted_at": None},
        _version_increment_update("access_version", {"deleted_at": now, "deleted_by": user["_id"], "updated_at": now}),
    )
    if result.matched_count != 1:
        raise HTTPException(404, "Cliente não encontrado")
    # Preserve every related record while immediately invalidating existing
    # restaurant sessions through their security-version binding.
    await db.tenant_users.update_many({"tenant_id": tid}, _version_increment_update("token_version", {}))
    await log_activity(actor_id=user["_id"], actor_name=user.get("name", user["email"]),
                       action="tenant.deleted", target_type="tenant", target_id=tid,
                       tenant_id=tid, metadata={"name": tenant.get("name", ""), "soft_delete": True})
    return {"ok": True}


# ─── Modules catalog ───────────────────────────────────────────────────────────
def _module_out(m: dict) -> dict:
    return {
        "id": str(m["_id"]), "key": m["key"], "name": m["name"],
        "description": m.get("description", ""),
        "status": m.get("status", "available"),
        "icon": m.get("icon", "package"),
        "category": m.get("category", ""),
        "launch_url_template": m.get("launch_url_template", ""),
    }


@api_router.get("/hub/modules")
async def list_modules(_u: dict = Depends(get_staff_user)):
    docs = await db.modules.find({}).to_list(200)
    return [_module_out(m) for m in docs]


class LaunchUrlTemplateIn(BaseModel):
    launch_url_template: str = Field(min_length=1, max_length=500)


def _validate_orders_launch_url_template(value: str) -> str:
    template = value.strip()
    if template.count("{slug}") != 1:
        raise HTTPException(400, "A URL do módulo Pedidos deve conter exatamente um placeholder {slug}")
    destination = template.replace("{slug}", "startup-check")
    if "{" in destination or "}" in destination:
        raise HTTPException(400, "A URL do módulo contém placeholders inválidos")
    validate_launch_url(destination, ORDERS_MODULE_KEY)
    return template


@api_router.patch("/hub/modules/orders/launch-url-template")
async def set_orders_launch_url_template(payload: LaunchUrlTemplateIn, user: dict = Depends(get_staff_write)):
    module = await db.modules.find_one({"key": ORDERS_MODULE_KEY})
    if not module:
        raise HTTPException(404, "Módulo Pedidos não encontrado")
    template = _validate_orders_launch_url_template(payload.launch_url_template)
    previous = module.get("launch_url_template", "")
    await db.modules.update_one({"_id": module["_id"]}, {"$set": {"launch_url_template": template}})
    await log_activity(
        actor_id=user["_id"], actor_name=user.get("name", user["email"]),
        action="module.launch_url_template_updated", target_type="module", target_id=ORDERS_MODULE_KEY,
        metadata={"previous_template": previous, "new_template": template},
    )
    module["launch_url_template"] = template
    return _module_out(module)


# ─── Tenant modules (activation) ───────────────────────────────────────────────
class LaunchUrlIn(BaseModel):
    launch_url: str


class ModuleUserGrantIn(BaseModel):
    active: bool


async def _orders_responsible_user(tid: str) -> Optional[dict]:
    return await db.tenant_users.find_one(
        {"tenant_id": tid, "status": "active", "role": {"$in": ["admin", "manager"]},
         "deleted_at": None},
        sort=[("role", 1), ("created_at", 1)],
    )


async def _provision_orders_tenant(tid: str, tenant: dict, activation: dict) -> None:
    responsible = await _orders_responsible_user(tid)
    now = now_utc().isoformat()
    if not responsible:
        await db.tenant_modules.update_one(
            {"tenant_id": tid, "module_key": ORDERS_MODULE_KEY},
            {"$set": {"provisioning_status": "failed", "provisioning_updated_at": now,
                      "provisioning_error": "responsible_user_missing"}, "$inc": {"provisioning_attempts": 1}},
        )
        raise HTTPException(409, "Crie um administrador ou gerente ativo antes de ativar Pedidos")

    uid = str(responsible["_id"])
    await db.module_user_grants.update_one(
        {"tenant_id": tid, "user_id": uid, "module_key": ORDERS_MODULE_KEY},
        {"$set": {"active": True, "source": "provisioning", "updated_at": now},
         "$setOnInsert": {"created_at": now}}, upsert=True,
    )
    await db.tenant_modules.update_one(
        {"tenant_id": tid, "module_key": ORDERS_MODULE_KEY},
        {"$set": {"provisioning_status": "pending", "provisioning_updated_at": now},
         "$unset": {"provisioning_error": ""}},
    )
    try:
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=False) as client:
            result = await client.post(
                f"{_orders_backend_url()}/api/internal/hub/provision",
                headers={"X-Module-Key": MODULE_ACCESS_KEYS[ORDERS_MODULE_KEY]},
                json={
                    "tenant_id": tid, "tenant_name": tenant["name"],
                    "hub_user_id": uid, "name": responsible["name"],
                    "email": responsible["email"], "role": responsible["role"],
                },
            )
        if result.status_code != 200:
            raise ValueError(f"orders_status_{result.status_code}")
        provisioned = result.json()
        invite_token = provisioned.get("invite_token")
        if invite_token and not await send_orders_first_access_email(responsible["email"], invite_token):
            await db.tenant_modules.update_one(
                {"tenant_id": tid, "module_key": ORDERS_MODULE_KEY},
                {"$set": {"provisioning_status": "failed", "provisioning_updated_at": now,
                          "provisioning_error": "email_delivery_failed"},
                 "$inc": {"provisioning_attempts": 1}},
            )
            raise HTTPException(503, "Usuário provisionado, mas o convite não foi enviado; tente novamente")
    except HTTPException:
        raise
    except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
        await db.tenant_modules.update_one(
            {"tenant_id": tid, "module_key": ORDERS_MODULE_KEY},
            {"$set": {"provisioning_status": "failed", "provisioning_updated_at": now,
                      "provisioning_error": type(exc).__name__}, "$inc": {"provisioning_attempts": 1}},
        )
        raise HTTPException(503, "Pedidos foi ativado, mas o provisionamento falhou; tente ativar novamente")
    await db.tenant_modules.update_one(
        {"tenant_id": tid, "module_key": ORDERS_MODULE_KEY},
        {"$set": {"provisioning_status": "succeeded", "provisioning_updated_at": now,
                  "provisioned_user_id": uid}, "$unset": {"provisioning_error": ""},
         "$inc": {"provisioning_attempts": 1}},
    )


@api_router.get("/hub/tenants/{tid}/modules")
async def tenant_modules(tid: str, _u: dict = Depends(get_staff_user)):
    if not ObjectId.is_valid(tid):
        raise HTTPException(404, "Cliente não encontrado")
    tenant = await db.tenants.find_one({"_id": ObjectId(tid), "deleted_at": None})
    if not tenant:
        raise HTTPException(404, "Cliente não encontrado")
    modules = await db.modules.find({}).to_list(200)
    activations = {a["module_key"]: a for a in await db.tenant_modules.find({"tenant_id": tid}).to_list(200)}
    out = []
    for m in modules:
        act = activations.get(m["key"])
        active = bool(act and act.get("active"))
        launch_url = ""
        if active:
            launch_url = (act.get("launch_url") or "").strip()
            if not launch_url and m.get("launch_url_template"):
                launch_url = m["launch_url_template"].replace("{slug}", tenant.get("slug", ""))
        out.append({
            **_module_out(m), "active": active,
            "activated_at": act.get("activated_at") if act else None,
            "launch_url": launch_url,
            "can_activate": m.get("status") == "available",
        })
    return out


@api_router.post("/hub/tenants/{tid}/modules/{mkey}/activate")
async def activate_module(tid: str, mkey: str, user: dict = Depends(get_staff_write)):
    if not ObjectId.is_valid(tid):
        raise HTTPException(404, "Cliente não encontrado")
    tenant = await db.tenants.find_one({"_id": ObjectId(tid), "deleted_at": None})
    if not tenant:
        raise HTTPException(404, "Cliente não encontrado")
    m = await db.modules.find_one({"key": mkey})
    if not m:
        raise HTTPException(404, "Módulo não encontrado")
    if m.get("status") != "available":
        raise HTTPException(400, "Módulo não está disponível para ativação")
    await db.tenant_modules.update_one(
        {"tenant_id": tid, "module_key": mkey},
        {"$set": {"active": True, "activated_at": now_utc().isoformat(),
                  "activated_by": user["_id"], "module_id": str(m["_id"])}},
        upsert=True,
    )
    if mkey == ORDERS_MODULE_KEY:
        activation = await db.tenant_modules.find_one({"tenant_id": tid, "module_key": mkey})
        await _provision_orders_tenant(tid, tenant, activation)
    await log_activity(actor_id=user["_id"], actor_name=user.get("name", user["email"]),
                       action="module.activated", target_type="module", target_id=mkey,
                       tenant_id=tid, metadata={"tenant_name": tenant["name"], "module": m["name"]})
    return {"ok": True}


@api_router.post("/hub/tenants/{tid}/modules/{mkey}/deactivate")
async def deactivate_module(tid: str, mkey: str, user: dict = Depends(get_staff_write)):
    if not ObjectId.is_valid(tid):
        raise HTTPException(404, "Cliente não encontrado")
    tenant = await db.tenants.find_one({"_id": ObjectId(tid), "deleted_at": None})
    if not tenant:
        raise HTTPException(404, "Cliente não encontrado")
    m = await db.modules.find_one({"key": mkey})
    if not m:
        raise HTTPException(404, "Módulo não encontrado")
    await db.tenant_modules.update_one(
        {"tenant_id": tid, "module_key": mkey},
        _version_increment_update("access_version", {"active": False, "deactivated_at": now_utc().isoformat()}),
    )
    await log_activity(actor_id=user["_id"], actor_name=user.get("name", user["email"]),
                       action="module.deactivated", target_type="module", target_id=mkey,
                       tenant_id=tid, metadata={"tenant_name": tenant["name"], "module": m["name"]})
    return {"ok": True}


@api_router.patch("/hub/tenants/{tid}/modules/{mkey}")
async def set_launch_url(tid: str, mkey: str, payload: LaunchUrlIn, _u: dict = Depends(get_staff_write)):
    if not ObjectId.is_valid(tid):
        raise HTTPException(404, "Cliente não encontrado")
    if not await db.tenants.find_one({"_id": ObjectId(tid), "deleted_at": None}) or not await db.modules.find_one({"key": mkey}):
        raise HTTPException(404, "Recurso não encontrado")
    destination = validate_launch_url(payload.launch_url, mkey)
    await db.tenant_modules.update_one(
        {"tenant_id": tid, "module_key": mkey},
        {"$set": {"launch_url": destination}},
        upsert=True,
    )
    return {"ok": True}


async def _orders_tenant_module(tid: str) -> tuple[dict, dict]:
    if not ObjectId.is_valid(tid):
        raise HTTPException(404, "Restaurante não encontrado")
    tenant = await db.tenants.find_one({"_id": ObjectId(tid), "deleted_at": None})
    module = await db.modules.find_one({"key": ORDERS_MODULE_KEY})
    if not tenant or not module:
        raise HTTPException(404, "Recurso não encontrado")
    return tenant, module


@api_router.get("/hub/tenants/{tid}/modules/orders/access-grants")
async def list_orders_access_grants(tid: str, _u: dict = Depends(get_staff_user)):
    await _orders_tenant_module(tid)
    docs = await db.module_user_grants.find({"tenant_id": tid, "module_key": ORDERS_MODULE_KEY}).to_list(500)
    return [{"user_id": d["user_id"], "active": bool(d.get("active")), "updated_at": d.get("updated_at")} for d in docs]


@api_router.put("/hub/tenants/{tid}/modules/orders/users/{uid}/access")
async def set_orders_user_access(tid: str, uid: str, payload: ModuleUserGrantIn,
                                 user: dict = Depends(get_staff_write)):
    tenant, module = await _orders_tenant_module(tid)
    if not ObjectId.is_valid(uid):
        raise HTTPException(404, "Usuário não encontrado")
    tenant_user = await db.tenant_users.find_one(
        {"_id": ObjectId(uid), "tenant_id": tid, "deleted_at": None}
    )
    if not tenant_user:
        raise HTTPException(404, "Usuário não pertence ao restaurante selecionado")
    if not _tenant_operational(tenant):
        raise HTTPException(400, "Restaurante não está operacional")
    if module.get("status") != "available":
        raise HTTPException(400, "Módulo Pedidos não está disponível")
    activation = await db.tenant_modules.find_one({"tenant_id": tid, "module_key": ORDERS_MODULE_KEY, "active": True})
    if not activation:
        raise HTTPException(400, "Pedidos não está ativo para este restaurante")
    now = now_utc().isoformat()
    await db.module_user_grants.update_one(
        {"tenant_id": tid, "user_id": uid, "module_key": ORDERS_MODULE_KEY},
        {"$set": {"active": payload.active, "updated_at": now, "updated_by": user["_id"], "source": "admin"},
         "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    await log_activity(
        actor_id=user["_id"], actor_name=user.get("name", user["email"]),
        action="module.user_access_granted" if payload.active else "module.user_access_revoked",
        target_type="module_user_grant", target_id=uid, tenant_id=tid,
        metadata={"module": ORDERS_MODULE_KEY, "tenant_name": tenant["name"]},
    )
    return {"user_id": uid, "active": payload.active}


# ─── Tenant users ──────────────────────────────────────────────────────────────
VALID_TENANT_USER_STATUS = {"active", "inactive"}


def _tenant_user_out(d: dict) -> dict:
    return {
        "id": str(d["_id"]), "name": d.get("name", ""), "email": d.get("email", ""),
        "role": d.get("role", ""), "status": d.get("status", "active"),
        "created_at": d.get("created_at"),
    }


class TenantUserIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    role: str
    password: Optional[str] = Field(default=None, min_length=6)


class TenantUserPatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    email: Optional[EmailStr] = None
    role: Optional[str] = None
    status: Optional[str] = None


@api_router.get("/hub/tenants/{tid}/users")
async def tenant_users(tid: str, _u: dict = Depends(get_staff_user)):
    if not ObjectId.is_valid(tid):
        raise HTTPException(404, "Cliente não encontrado")
    if not await db.tenants.find_one({"_id": ObjectId(tid), "deleted_at": None}):
        raise HTTPException(404, "Cliente não encontrado")
    docs = await db.tenant_users.find(
        {"tenant_id": tid, "deleted_at": None}
    ).sort("created_at", -1).to_list(500)
    return [_tenant_user_out(d) for d in docs]


async def _create_tenant_user(tid: str, payload: TenantUserIn, actor: dict) -> dict:
    tenant = await db.tenants.find_one({"_id": ObjectId(tid), "deleted_at": None})
    if not tenant:
        raise HTTPException(404, "Cliente não encontrado")
    if payload.role not in VALID_HANDOFF_ROLES:
        raise HTTPException(400, "Papel inválido")
    name = payload.name.strip()
    if not name:
        raise HTTPException(400, "Nome é obrigatório")
    email = payload.email.lower()
    if await _email_in_use(email):
        raise HTTPException(409, "Já existe um usuário com este e-mail")
    generated_password = None if payload.password else secrets.token_urlsafe(9)
    doc = {
        "tenant_id": tid, "name": name, "email": email,
        "role": payload.role, "status": "active",
        "password_hash": hash_password(payload.password or generated_password),
        "user_type": "restaurant", "token_version": 0,
        "created_at": now_utc().isoformat(),
    }
    try:
        res = await db.tenant_users.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(409, "Já existe um usuário com este e-mail")
    doc["_id"] = res.inserted_id
    await log_activity(actor_id=actor["_id"], actor_name=actor.get("name", actor["email"]),
                       action="tenant_user.created", target_type="tenant_user",
                       target_id=str(res.inserted_id), tenant_id=tid,
                       metadata={"email": email, "role": payload.role})
    out = _tenant_user_out(doc)
    out["temp_password"] = generated_password
    return out


async def _create_initial_tenant_manager(tid: str, name: str, email: str) -> str:
    """Persist the invite-only first manager without ever exposing a password.

    This is intentionally separate from the legacy user-creation helper: its
    audit write happens after the complete onboarding succeeds, so a failure
    can compensate every document created by this request.
    """
    if await _email_in_use(email):
        raise HTTPException(409, "Já existe um usuário com este e-mail")
    doc = {
        "tenant_id": tid, "name": name, "email": email,
        "role": "manager", "status": "active", "user_type": "restaurant",
        # A random unusable credential satisfies the legacy schema only; the
        # reset-required flag blocks login until the invite link sets a password.
        "password_hash": hash_password(secrets.token_urlsafe(32)), "password_reset_required": True,
        "token_version": 0, "created_at": now_utc().isoformat(),
    }
    try:
        result = await db.tenant_users.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(409, "Já existe um usuário com este e-mail")
    return str(result.inserted_id)


@api_router.post("/hub/tenants/{tid}/users")
async def create_tenant_user(tid: str, payload: TenantUserIn, user: dict = Depends(get_staff_write)):
    if not ObjectId.is_valid(tid):
        raise HTTPException(404, "Cliente não encontrado")
    return await _create_tenant_user(tid, payload, user)


async def _acquire_tenant_admin_lock(tid: str) -> str:
    """Short Mongo-backed lease serializes last-admin checks across app workers."""
    owner = secrets.token_urlsafe(16)
    for _ in range(50):
        now = now_utc()
        tenant = await db.tenants.find_one_and_update(
            {"_id": ObjectId(tid), "deleted_at": None, "$or": [
                {"tenant_user_lock_expires_at": {"$lte": now}},
                {"tenant_user_lock_expires_at": {"$exists": False}},
            ]},
            {"$set": {"tenant_user_lock_owner": owner,
                      "tenant_user_lock_expires_at": now + timedelta(seconds=10)}},
            return_document=ReturnDocument.AFTER,
        )
        if tenant:
            return owner
        await asyncio.sleep(0.1)
    raise HTTPException(409, "Outra alteração de administradores está em andamento. Tente novamente.")


async def _release_tenant_admin_lock(tid: str, owner: str) -> None:
    await db.tenants.update_one(
        {"_id": ObjectId(tid), "tenant_user_lock_owner": owner},
        {"$unset": {"tenant_user_lock_owner": "", "tenant_user_lock_expires_at": ""}},
    )


async def _apply_tenant_user_patch(tid: str, uid: str, payload: TenantUserPatch,
                                   actor: dict) -> dict:
    if not ObjectId.is_valid(tid) or not ObjectId.is_valid(uid):
        raise HTTPException(404, "Usuário não encontrado")
    if not await db.tenants.find_one({"_id": ObjectId(tid), "deleted_at": None}):
        raise HTTPException(404, "Cliente não encontrado")
    oid = ObjectId(uid)
    existing = await db.tenant_users.find_one(
        {"_id": oid, "tenant_id": tid, "deleted_at": None}
    )
    if not existing:
        raise HTTPException(404, "Usuário não encontrado")
    update = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    if "name" in update:
        update["name"] = update["name"].strip()
        if not update["name"]:
            raise HTTPException(400, "Nome é obrigatório")
    if "email" in update:
        email = update["email"].lower()
        if await _email_in_use(email, exclude_collection="tenant_users", exclude_id=oid):
            raise HTTPException(409, "Já existe um usuário com este e-mail")
        update["email"] = email
    if "role" in update and update["role"] not in VALID_HANDOFF_ROLES:
        raise HTTPException(400, "Papel inválido")
    if "status" in update and update["status"] not in VALID_TENANT_USER_STATUS:
        raise HTTPException(400, "Status inválido")
    if (actor.get("user_type") == "restaurant" and actor["_id"] == uid
            and ("role" in update or update.get("status") == "inactive")):
        raise HTTPException(400, "Você não pode alterar seu próprio papel nem desativar sua própria conta")

    lock_owner = None
    try:
        removes_admin = (existing.get("status", "active") == "active"
                         and existing.get("role") == "admin"
                         and (update.get("status", existing.get("status", "active")) != "active"
                              or update.get("role", existing.get("role")) != "admin"))
        if removes_admin:
            lock_owner = await _acquire_tenant_admin_lock(tid)
            existing = await db.tenant_users.find_one(
                {"_id": oid, "tenant_id": tid, "deleted_at": None}
            )
            still_removes_admin = (existing and existing.get("status", "active") == "active"
                                   and existing.get("role") == "admin"
                                   and (update.get("status", existing.get("status", "active")) != "active"
                                        or update.get("role", existing.get("role")) != "admin"))
            if still_removes_admin:
                active_admins = await db.tenant_users.count_documents(
                    {"tenant_id": tid, "status": "active", "role": "admin",
                     "deleted_at": None})
                if active_admins <= 1:
                    raise HTTPException(400, "O restaurante precisa manter pelo menos um administrador ativo")

        if update:
            mutation = {"$set": update}
            if "status" in update or "role" in update:
                mutation = _version_increment_update("token_version", update)
            try:
                await db.tenant_users.update_one(
                    {"_id": oid, "tenant_id": tid, "deleted_at": None}, mutation
                )
            except DuplicateKeyError:
                raise HTTPException(409, "Já existe um usuário com este e-mail")
            if "status" in update or "role" in update:
                await revoke_user_sessions(
                    db, user_id=uid, user_type="restaurant", reason="account_security_changed"
                )
    finally:
        if lock_owner:
            await _release_tenant_admin_lock(tid, lock_owner)

    if update:
        await log_activity(actor_id=actor["_id"], actor_name=actor.get("name", actor["email"]),
                           action="tenant_user.updated", target_type="tenant_user",
                           target_id=uid, tenant_id=tid,
                           metadata={k: update[k] for k in ("name", "email", "role", "status") if k in update})
    return _tenant_user_out(await db.tenant_users.find_one(
        {"_id": oid, "tenant_id": tid, "deleted_at": None}
    ))


async def _reset_tenant_user_password(tid: str, uid: str, actor: dict) -> dict:
    if not ObjectId.is_valid(tid) or not ObjectId.is_valid(uid):
        raise HTTPException(404, "Usuário não encontrado")
    if not await db.tenants.find_one({"_id": ObjectId(tid), "deleted_at": None}):
        raise HTTPException(404, "Cliente não encontrado")
    if actor.get("user_type") == "restaurant" and actor["_id"] == uid:
        raise HTTPException(400, "Use a recuperação de senha para alterar sua própria senha")
    generated_password = secrets.token_urlsafe(12)
    result = await db.tenant_users.update_one(
        {"_id": ObjectId(uid), "tenant_id": tid, "deleted_at": None},
        _version_increment_update("token_version", {"password_hash": hash_password(generated_password),
                                                     "password_reset_required": False}),
    )
    if result.matched_count != 1:
        raise HTTPException(404, "Usuário não encontrado")
    await revoke_user_sessions(db, user_id=uid, user_type="restaurant", reason="password_reset")
    await log_activity(actor_id=actor["_id"], actor_name=actor.get("name", actor["email"]),
                       action="tenant_user.password_reset", target_type="tenant_user",
                       target_id=uid, tenant_id=tid)
    return {"temp_password": generated_password}


@api_router.patch("/hub/tenants/{tid}/users/{uid}")
async def patch_tenant_user(tid: str, uid: str, payload: TenantUserPatch,
                            user: dict = Depends(get_staff_write)):
    return await _apply_tenant_user_patch(tid, uid, payload, user)


@api_router.post("/hub/tenants/{tid}/users/{uid}/reset-password")
async def reset_tenant_user_password(tid: str, uid: str, user: dict = Depends(get_staff_write)):
    return await _reset_tenant_user_password(tid, uid, user)


@api_router.delete("/hub/tenants/{tid}/users/{uid}")
async def delete_tenant_user(tid: str, uid: str, user: dict = Depends(get_staff_write)):
    """Logically remove one restaurant identity without erasing its history."""
    if not ObjectId.is_valid(tid) or not ObjectId.is_valid(uid):
        raise HTTPException(404, "Usuário não encontrado")
    if not await db.tenants.find_one({"_id": ObjectId(tid), "deleted_at": None}):
        raise HTTPException(404, "Cliente não encontrado")
    oid = ObjectId(uid)
    existing = await db.tenant_users.find_one(
        {"_id": oid, "tenant_id": tid, "deleted_at": None}
    )
    if not existing:
        raise HTTPException(404, "Usuário não encontrado")

    lock_owner = None
    try:
        if existing.get("status", "active") == "active" and existing.get("role") == "admin":
            lock_owner = await _acquire_tenant_admin_lock(tid)
            existing = await db.tenant_users.find_one(
                {"_id": oid, "tenant_id": tid, "deleted_at": None}
            )
            active_admins = await db.tenant_users.count_documents(
                {"tenant_id": tid, "status": "active", "role": "admin",
                 "deleted_at": None}
            )
            if existing and active_admins <= 1:
                raise HTTPException(400, "O restaurante precisa manter pelo menos um administrador ativo")

        now = now_utc().isoformat()
        result = await db.tenant_users.update_one(
            {"_id": oid, "tenant_id": tid, "deleted_at": None},
            _version_increment_update("token_version", {"deleted_at": now, "deleted_by": user["_id"]}),
        )
        if result.matched_count != 1:
            raise HTTPException(404, "Usuário não encontrado")
    finally:
        if lock_owner:
            await _release_tenant_admin_lock(tid, lock_owner)

    await revoke_user_sessions(db, user_id=uid, user_type="restaurant", reason="account_deleted")
    await log_activity(
        actor_id=user["_id"], actor_name=user.get("name", user["email"]),
        action="tenant_user.deleted", target_type="tenant_user", target_id=uid, tenant_id=tid,
        metadata={"name": existing.get("name", ""), "email": existing.get("email", ""), "soft_delete": True},
    )
    return {"ok": True}


# ─── Hub users (DACOT internal staff) ──────────────────────────────────────────
VALID_HUB_ROLES = HUB_ADMIN_ROLES | {"viewer"}


def _hub_user_out(d: dict) -> dict:
    return {
        "id": str(d["_id"]), "name": d.get("name", ""), "email": d.get("email", ""),
        "role": d.get("role", "viewer"), "active": d.get("active", True),
        "created_at": d.get("created_at"),
    }


class HubUserIn(BaseModel):
    name: str
    email: EmailStr
    role: str
    password: Optional[str] = Field(default=None, min_length=6)


class HubUserPatch(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    role: Optional[str] = None
    active: Optional[bool] = None


async def _active_admin_count(exclude_id: Optional[ObjectId] = None) -> int:
    query: dict = {"active": True, "role": {"$in": list(HUB_ADMIN_ROLES)}, "deleted_at": None}
    if exclude_id is not None:
        query["_id"] = {"$ne": exclude_id}
    return await db.hub_users.count_documents(query)


async def _active_super_admin_count(exclude_id: Optional[ObjectId] = None) -> int:
    query: dict = {"active": True, "role": "super_admin", "deleted_at": None}
    if exclude_id is not None:
        query["_id"] = {"$ne": exclude_id}
    return await db.hub_users.count_documents(query)


@api_router.get("/hub/users")
async def list_hub_users(_u: dict = Depends(get_staff_user)):
    docs = await db.hub_users.find({"deleted_at": None}).sort("created_at", -1).to_list(500)
    return [_hub_user_out(d) for d in docs]


@api_router.post("/hub/users")
async def create_hub_user(payload: HubUserIn, user: dict = Depends(get_staff_write)):
    if payload.role not in VALID_HUB_ROLES:
        raise HTTPException(400, "Papel inválido")
    if payload.role == "super_admin" and user.get("role") != "super_admin":
        raise HTTPException(403, "Apenas super administradores podem criar outro super administrador")
    email = payload.email.lower()
    if await _email_in_use(email):
        raise HTTPException(409, "Já existe um usuário com este e-mail")
    generated_password = None if payload.password else secrets.token_urlsafe(9)
    doc = {
        "email": email, "name": payload.name.strip(), "role": payload.role,
        "password_hash": hash_password(payload.password or generated_password),
        "user_type": "staff", "active": True, "token_version": 0,
        "created_at": now_utc().isoformat(),
    }
    res = await db.hub_users.insert_one(doc)
    doc["_id"] = res.inserted_id
    await log_activity(actor_id=user["_id"], actor_name=user.get("name", user["email"]),
                       action="hub_user.created", target_type="hub_user",
                       target_id=str(res.inserted_id), metadata={"email": email, "role": payload.role})
    out = _hub_user_out(doc)
    out["temp_password"] = generated_password
    return out


@api_router.patch("/hub/users/{uid}")
async def patch_hub_user(uid: str, payload: HubUserPatch, user: dict = Depends(get_staff_write)):
    if not ObjectId.is_valid(uid):
        raise HTTPException(404, "Usuário não encontrado")
    existing = await db.hub_users.find_one({"_id": ObjectId(uid), "deleted_at": None})
    if not existing:
        raise HTTPException(404, "Usuário não encontrado")
    update = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    is_self = uid == user["_id"]

    if "email" in update:
        email = update["email"].lower()
        if await _email_in_use(email, exclude_collection="hub_users", exclude_id=ObjectId(uid)):
            raise HTTPException(409, "Já existe um usuário com este e-mail")
        update["email"] = email
    if "role" in update and update["role"] not in VALID_HUB_ROLES:
        raise HTTPException(400, "Papel inválido")
    if existing.get("role") == "super_admin" and user.get("role") != "super_admin":
        raise HTTPException(403, "Apenas super administradores podem alterar outro super administrador")
    if update.get("role") == "super_admin" and user.get("role") != "super_admin":
        raise HTTPException(403, "Apenas super administradores podem promover outro super administrador")

    # Self-lockout / "last admin standing" guard: never let a change strip
    # admin capability from a currently-active admin/super_admin when it
    # would either be done to one's own account (always blocked — use
    # another admin account) or would leave zero active admins anywhere.
    was_admin = existing.get("active", True) and existing.get("role") in HUB_ADMIN_ROLES
    will_deactivate = update.get("active") is False
    will_demote = "role" in update and update["role"] not in HUB_ADMIN_ROLES
    if was_admin and (will_deactivate or will_demote):
        if is_self:
            raise HTTPException(400, "Você não pode desativar sua própria conta nem remover sua própria permissão administrativa.")
        if await _active_admin_count(exclude_id=ObjectId(uid)) == 0:
            raise HTTPException(400, "Essa alteração deixaria o sistema sem nenhum administrador ativo.")

    if update:
        await db.hub_users.update_one({"_id": ObjectId(uid), "deleted_at": None}, {"$set": update})
    if "active" in update or "role" in update:
        await revoke_user_sessions(db, user_id=uid, user_type="staff", reason="account_security_changed")
    if "active" in update or "role" in update:
        await log_activity(actor_id=user["_id"], actor_name=user.get("name", user["email"]),
                           action="hub_user.updated", target_type="hub_user", target_id=uid,
                           metadata={k: update[k] for k in ("active", "role") if k in update})
    d = await db.hub_users.find_one({"_id": ObjectId(uid), "deleted_at": None})
    return _hub_user_out(d)


@api_router.delete("/hub/users/{uid}")
async def delete_hub_user(uid: str, user: dict = Depends(get_staff_write)):
    if not ObjectId.is_valid(uid):
        raise HTTPException(404, "Usuário não encontrado")
    if uid == user["_id"]:
        raise HTTPException(400, "Você não pode excluir sua própria conta")
    oid = ObjectId(uid)
    existing = await db.hub_users.find_one({"_id": oid, "deleted_at": None})
    if not existing:
        raise HTTPException(404, "Usuário não encontrado")
    if existing.get("role") == "super_admin":
        if user.get("role") != "super_admin":
            raise HTTPException(403, "Apenas super administradores podem excluir outro super administrador")
        if await _active_super_admin_count(exclude_id=oid) == 0:
            raise HTTPException(400, "O sistema precisa manter pelo menos um super administrador ativo")
    now = now_utc().isoformat()
    result = await db.hub_users.update_one(
        {"_id": oid, "deleted_at": None},
        _version_increment_update("token_version", {"active": False, "deleted_at": now, "deleted_by": user["_id"]}),
    )
    if result.matched_count != 1:
        raise HTTPException(404, "Usuário não encontrado")
    await revoke_user_sessions(db, user_id=uid, user_type="staff", reason="account_deleted")
    await log_activity(
        actor_id=user["_id"], actor_name=user.get("name", user["email"]),
        action="hub_user.deleted", target_type="hub_user", target_id=uid,
        metadata={"email": existing.get("email", ""), "role": existing.get("role", ""), "soft_delete": True},
    )
    return {"ok": True}


# ─── Dashboard ─────────────────────────────────────────────────────────────────
@api_router.get("/hub/dashboard/stats")
async def dashboard_stats(_u: dict = Depends(get_staff_user)):
    visible_tenants = {"deleted_at": None}
    active = await db.tenants.count_documents({**visible_tenants, "status": "active"})
    trial = await db.tenants.count_documents({**visible_tenants, "status": "trial"})
    suspended = await db.tenants.count_documents({**visible_tenants, "status": "suspended"})
    inactive = await db.tenants.count_documents({**visible_tenants, "status": "inactive"})
    total = await db.tenants.count_documents(visible_tenants)
    active_mods = await db.tenant_modules.count_documents({"active": True})
    total_users = await db.tenant_users.count_documents({"deleted_at": None})
    # per-module activation counts
    modules = await db.modules.find({}).to_list(200)
    per_module = []
    for m in modules:
        cnt = await db.tenant_modules.count_documents({"module_key": m["key"], "active": True})
        per_module.append({"key": m["key"], "name": m["name"],
                           "status": m.get("status"), "activations": cnt})
    return {
        "active": active, "trial": trial, "suspended": suspended, "inactive": inactive,
        "total_tenants": total, "active_modules": active_mods, "total_users": total_users,
        "per_module": per_module,
    }


@api_router.get("/hub/dashboard/activity")
async def dashboard_activity(limit: int = 15, _u: dict = Depends(get_staff_user)):
    docs = await db.activity_log.find({}).sort("created_at", -1).limit(limit).to_list(limit)
    return [{
        "id": str(d["_id"]), "actor_name": d.get("actor_name", ""),
        "action": d.get("action", ""), "target_type": d.get("target_type", ""),
        "target_id": d.get("target_id"), "tenant_id": d.get("tenant_id"),
        "metadata": d.get("metadata", {}), "created_at": d.get("created_at"),
    } for d in docs]


# ─── Module handoff (Launch Token) ─────────────────────────────────────────────
@api_router.post("/hub/tenants/{tid}/modules/{mkey}/launch-token")
async def launch_token(tid: str, mkey: str,
                       user: dict = Depends(get_staff_write)):
    raise HTTPException(403, "Acesso operacional exige usuário do próprio restaurante; suporte DACOT não faz parte do V1.")


# ─── Public module status (module-to-module) ───────────────────────────────────
def require_module_key(mkey: str, request: Request):
    provided = request.headers.get("X-Module-Key", "")
    expected = MODULE_ACCESS_KEYS.get(mkey, "")
    if not expected or not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(401, "Chave de módulo inválida")


@api_router.get("/public/tenants/{tid}/modules/{mkey}/status")
async def public_module_status(tid: str, mkey: str, request: Request):
    require_module_key(mkey, request)
    if not ObjectId.is_valid(tid):
        raise HTTPException(404, "Recurso não encontrado")
    tenant = await db.tenants.find_one({"_id": ObjectId(tid)})
    if not tenant:
        raise HTTPException(404, "Recurso não encontrado")
    module = await db.modules.find_one({"key": mkey})
    if not module:
        raise HTTPException(404, "Recurso não encontrado")
    act = await db.tenant_modules.find_one(
        {"tenant_id": tid, "module_key": mkey, "active": True}
    )
    if not act or not _tenant_operational(tenant) or module.get("status") != "available":
        return {"active": False, "module": mkey}
    return {
        "active": True,
        "module": mkey,
        "activated_at": act.get("activated_at"),
    }


class AccessVersions(BaseModel):
    user: int = Field(ge=0, strict=True)
    tenant: int = Field(ge=0, strict=True)
    module: int = Field(ge=0, strict=True)


class ModuleAccessIn(BaseModel):
    subject: str
    role: str
    hub_access: AccessVersions


class ModuleAccessContextIn(BaseModel):
    subject: str
    role: str


async def _current_module_access(tid: str, mkey: str, subject: str, role: str) -> Optional[dict]:
    if mkey != "orders" or not ObjectId.is_valid(tid) or not subject.startswith("tenant_user:"):
        return None
    uid = subject.removeprefix("tenant_user:")
    if not ObjectId.is_valid(uid):
        return None
    tenant = await db.tenants.find_one({"_id": ObjectId(tid)})
    module = await db.modules.find_one({"key": mkey})
    activation = await db.tenant_modules.find_one({"tenant_id": tid, "module_key": mkey, "active": True})
    user = await db.tenant_users.find_one(
        {"_id": ObjectId(uid), "tenant_id": tid, "deleted_at": None}
    )
    grant = await db.module_user_grants.find_one(
        {"tenant_id": tid, "user_id": uid, "module_key": ORDERS_MODULE_KEY, "active": True}
    )
    if (not tenant or not _tenant_operational(tenant) or not module or module.get("status") != "available"
            or not activation or not user or not grant or user.get("status") != "active"
            or user.get("password_reset_required") or not user.get("password_hash")
            or user.get("role") not in VALID_HANDOFF_ROLES or user.get("role") != role):
        return None
    versions = {"user": _security_version(user, "token_version"),
                "tenant": _security_version(tenant, "access_version"),
                "module": _security_version(activation, "access_version")}
    return None if any(value is None for value in versions.values()) else versions


@api_router.post("/public/tenants/{tid}/modules/{mkey}/access-context")
async def module_access_context(tid: str, mkey: str, payload: ModuleAccessContextIn,
                                request: Request, response: Response):
    require_module_key(mkey, request)
    response.headers["Cache-Control"] = "no-store"
    current = await _current_module_access(tid, mkey, payload.subject, payload.role)
    return {"active": bool(current), "hub_access": current} if current else {"active": False}


@api_router.post("/public/tenants/{tid}/modules/{mkey}/access")
async def module_access(tid: str, mkey: str, payload: ModuleAccessIn, request: Request, response: Response):
    """Authoritative, uncached check. Caller caches only a bounded positive lease."""
    require_module_key(mkey, request)
    response.headers["Cache-Control"] = "no-store"
    denied = {"active": False}
    current = await _current_module_access(tid, mkey, payload.subject, payload.role)
    if current is None:
        return denied
    return {"active": current == payload.hub_access.model_dump()}


# ─── Portal do Cliente (restaurant users) ─────────────────────────────────────
# Tenant isolation: tenant_id comes ONLY from the authenticated identity (DB),
# never from path/query/body. Restaurant users cannot reach /api/hub/* at all.
@api_router.get("/portal/context")
async def portal_context(user: dict = Depends(get_restaurant_user)):
    tid = user["tenant_id"]
    tenant = user["tenant"]  # resolved + operational check already done by get_restaurant_user
    modules = await db.modules.find({}).to_list(200)
    activations = {a["module_key"]: a for a in await db.tenant_modules.find(
        {"tenant_id": tid, "active": True}).to_list(200)}
    out = []
    for m in modules:
        act = activations.get(m["key"])
        active = bool(act)
        # Portal consumers receive only products released, available and
        # activated for their own tenant. Administrative catalog details and
        # launch URLs remain server-side until a handoff is requested.
        if m["key"] != ORDERS_MODULE_KEY or not active or m.get("status") != "available":
            continue
        out.append({**_module_out(m), "active": True})
    return {
        "user": {"id": user["_id"], "name": user.get("name"), "email": user["email"],
                 "role": user.get("role", "waiter")},
        "tenant": {"id": tid, "name": tenant["name"], "slug": tenant.get("slug", ""),
                   "status": tenant.get("status", "trial")},
        "modules": out,
    }


@api_router.get("/portal/analytics/revenue")
async def portal_revenue(response: Response, user: dict = Depends(get_restaurant_user)):
    """Return only Pedidos aggregates for the authenticated restaurant."""
    if not HANDOFF_JWT_SECRET or len(HANDOFF_JWT_SECRET) < 32:
        raise HTTPException(503, "Faturamento indisponível no momento")
    tid = user["tenant_id"]
    module = await db.modules.find_one({"key": ORDERS_MODULE_KEY})
    activation = await db.tenant_modules.find_one(
        {"tenant_id": tid, "module_key": ORDERS_MODULE_KEY, "active": True}
    )
    grant = await db.module_user_grants.find_one(
        {"tenant_id": tid, "user_id": user["_id"], "module_key": ORDERS_MODULE_KEY, "active": True}
    )
    if not module or module.get("status") != "available" or not activation or not grant:
        raise HTTPException(403, "Módulo Pedidos não está disponível para este usuário")

    now = now_utc()
    assertion = jwt.encode({
        "iss": HANDOFF_ISSUER, "aud": ORDERS_ANALYTICS_AUDIENCE,
        "restaurant_id": tid, "module": ORDERS_MODULE_KEY, "scope": ORDERS_ANALYTICS_SCOPE,
        "jti": secrets.token_urlsafe(16),
        "iat": int(now.timestamp()), "nbf": int(now.timestamp()) - 5,
        "exp": int((now + timedelta(seconds=HANDOFF_MAX_TTL_SECONDS)).timestamp()),
    }, HANDOFF_JWT_SECRET, algorithm="HS256")
    try:
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=False) as client:
            result = await client.get(
                f"{_orders_backend_url()}/api/internal/analytics/revenue",
                headers={"Authorization": f"Bearer {assertion}"},
            )
        if result.status_code != 200:
            raise ValueError("Pedidos rejected analytics assertion")
        payload = result.json()
        required = {"today_cents", "current_month_cents", "currency", "timezone"}
        if (set(payload) != required or payload["currency"] != "BRL"
                or payload["timezone"] != "America/Sao_Paulo"
                or any(type(payload[field]) is not int or payload[field] < 0
                       for field in ("today_cents", "current_month_cents"))):
            raise ValueError("Invalid Pedidos analytics response")
    except (httpx.HTTPError, ValueError, TypeError, KeyError):
        raise HTTPException(503, "Faturamento indisponível no momento")
    response.headers["Cache-Control"] = "no-store"
    return payload


@api_router.get("/portal/users")
async def portal_users(user: dict = Depends(get_restaurant_admin)):
    docs = await db.tenant_users.find(
        {"tenant_id": user["tenant_id"], "deleted_at": None}
    ).sort("created_at", -1).to_list(500)
    return [_tenant_user_out(d) for d in docs]


@api_router.post("/portal/users")
async def create_portal_user(payload: TenantUserIn, user: dict = Depends(get_restaurant_admin)):
    # tenant_id is deliberately derived from the authenticated database identity.
    return await _create_tenant_user(user["tenant_id"], payload, user)


@api_router.patch("/portal/users/{uid}")
async def patch_portal_user(uid: str, payload: TenantUserPatch,
                            user: dict = Depends(get_restaurant_admin)):
    return await _apply_tenant_user_patch(user["tenant_id"], uid, payload, user)


@api_router.post("/portal/users/{uid}/reset-password")
async def reset_portal_user_password(uid: str, user: dict = Depends(get_restaurant_admin)):
    return await _reset_tenant_user_password(user["tenant_id"], uid, user)


@api_router.post("/portal/modules/{mkey}/launch-token")
async def portal_launch_token(mkey: str, user: dict = Depends(get_restaurant_user)):
    # Handoff represents the RESTAURANT user: restaurant_id and role are derived
    # exclusively from the authenticated identity — the request carries no authority.
    if not HANDOFF_JWT_SECRET or len(HANDOFF_JWT_SECRET) < 32:
        raise HTTPException(500, "Segredo de handoff não configurado no servidor")
    tid = user["tenant_id"]
    tenant = user["tenant"]  # resolved + operational check already done by get_restaurant_user
    module = await db.modules.find_one({"key": mkey})
    if not module:
        raise HTTPException(404, "Módulo não encontrado")
    activation = await db.tenant_modules.find_one(
        {"tenant_id": tid, "module_key": mkey, "active": True}
    )
    if not activation or module.get("status") != "available":
        raise HTTPException(400, "Módulo não está ativo para o seu restaurante")
    versions = {"user": _security_version(user, "token_version"),
                "tenant": _security_version(tenant, "access_version"),
                "module": _security_version(activation, "access_version")}
    if any(value is None for value in versions.values()):
        raise HTTPException(403, "Versão de acesso inválida")
    if user.get("role") not in VALID_HANDOFF_ROLES:
        raise HTTPException(403, "Papel operacional inválido")
    if mkey == ORDERS_MODULE_KEY:
        grant = await db.module_user_grants.find_one(
            {"tenant_id": tid, "user_id": user["_id"], "module_key": mkey, "active": True}
        )
        if not grant:
            raise HTTPException(403, "Usuário não possui acesso a este módulo")
    role = user["role"]
    launch_url = (activation.get("launch_url") or "").strip()
    if not launch_url and module.get("launch_url_template"):
        launch_url = module["launch_url_template"].replace("{slug}", tenant.get("slug", ""))
    launch_url = validate_launch_url(launch_url, mkey)

    aud = HANDOFF_AUDIENCE.get(mkey, f"dacot-{mkey}")
    now = now_utc()
    exp = now + timedelta(seconds=HANDOFF_MAX_TTL_SECONDS)
    jti = secrets.token_urlsafe(16)
    claims = {
        "iss": HANDOFF_ISSUER,
        "aud": aud,
        "sub": f"tenant_user:{user['_id']}",
        "hub_access": versions,
        "restaurant_id": tid,                        # own tenant, server-signed
        "restaurant_slug": tenant.get("slug", ""),
        "role": role,                                # operational role from DB
        "module": mkey,
        "jti": jti,
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()) - 5,
        "exp": int(exp.timestamp()),
        "handoff_version": HANDOFF_VERSION,
    }
    token = jwt.encode(claims, HANDOFF_JWT_SECRET, algorithm="HS256")
    await log_activity(
        actor_id=user["_id"], actor_name=user.get("name", user["email"]),
        action="module.launch_token_issued", target_type="module",
        target_id=mkey, tenant_id=tid,
        metadata={"module": module["name"], "jti": jti, "aud": aud,
                  "role": role, "via": "portal"},
    )
    return {
        "handoff": token,
        "launch_url": launch_url,
        "expires_in": HANDOFF_MAX_TTL_SECONDS,
        "expires_at": exp.isoformat(),
        "jti": jti,
    }


# ─── Health ────────────────────────────────────────────────────────────────────
@api_router.get("/")
async def root():
    return {"service": "DACOT Hub API", "ok": True}


# ─── Startup: indexes + seed ───────────────────────────────────────────────────
DEFAULT_MODULES = [
    {"key": "orders", "name": "Pedidos", "status": "available", "icon": "clipboard-list",
     "category": "Operacional",
     "description": "Sistema para criação, acompanhamento e gerenciamento de pedidos do restaurante.",
     "launch_url_template": ORDERS_LAUNCH_URL_TEMPLATE},
    {"key": "kitchen", "name": "Cozinha", "status": "available", "icon": "chef-hat",
     "category": "Operacional",
     "description": "Área operacional para acompanhamento e atualização dos pedidos pela cozinha.",
     "launch_url_template": "https://cozinha.dacot.app/{slug}"},
    {"key": "customers", "name": "Clientes", "status": "in_development", "icon": "users",
     "category": "CRM",
     "description": "Cadastro e histórico de clientes, com preferências e programa de fidelidade.",
     "launch_url_template": ""},
    {"key": "inventory", "name": "Estoque", "status": "in_development", "icon": "boxes",
     "category": "Operacional",
     "description": "Controle de insumos, movimentações e alertas de reposição.",
     "launch_url_template": ""},
    {"key": "finance", "name": "Financeiro", "status": "in_development", "icon": "landmark",
     "category": "Gestão",
     "description": "Fluxo de caixa, contas a pagar/receber e conciliação de vendas.",
     "launch_url_template": ""},
    {"key": "delivery", "name": "Delivery", "status": "planned", "icon": "bike",
     "category": "Operacional",
     "description": "Gestão de entregas, rotas e integração com plataformas de delivery.",
     "launch_url_template": ""},
]

@app.on_event("startup")
async def startup():
    validate_handoff_configuration(
        HANDOFF_JWT_SECRET, HANDOFF_ISSUER, HANDOFF_AUDIENCE,
        HANDOFF_VERSION, MODULE_ACCESS_KEYS,
    )
    if os.environ.get("APP_ENV", "production").strip().lower() == "production":
        _orders_frontend_url()
        orders_template = next(m["launch_url_template"] for m in DEFAULT_MODULES if m["key"] == "orders")
        validate_launch_url(orders_template.replace("{slug}", "startup-check"), "orders")
    logger.info("Verificando conexão com MongoDB durante a inicialização")
    try:
        await asyncio.wait_for(db.command("ping"), timeout=MONGO_STARTUP_TIMEOUT_SECONDS)
    except (asyncio.TimeoutError, PyMongoError) as exc:
        raise RuntimeError("MongoDB não ficou disponível durante a inicialização") from exc
    logger.info("MongoDB disponível; criando índices e aplicando migrações de startup")
    await db.hub_users.create_index("email", unique=True)
    await db.tenants.create_index("email")
    await db.tenants.create_index("slug", unique=True)
    await db.modules.create_index("key", unique=True)
    await db.tenant_modules.create_index([("tenant_id", 1), ("module_key", 1)], unique=True)
    await db.tenant_users.create_index("tenant_id")
    await db.tenant_users.create_index("email", unique=True)
    await db.activity_log.create_index([("created_at", -1)])
    await db.login_attempts.create_index("email")
    await db.login_attempts.create_index("identifier")
    await db.password_reset_tokens.create_index("token_hash", unique=True)
    await db.password_reset_tokens.create_index("expires_at", expireAfterSeconds=0)
    await db.password_reset_requests.create_index("email")
    await db.password_reset_requests.create_index("created_at", expireAfterSeconds=900)
    await db.password_reset_cooldowns.create_index("last_allowed", expireAfterSeconds=3600)
    await ensure_indexes(db)

    # Seed admin
    admin_email = os.environ["ADMIN_EMAIL"].lower()
    existing = await db.hub_users.find_one({"email": admin_email})
    if not existing:
        admin_pw = os.environ["ADMIN_PASSWORD"]
        if await _email_in_use(admin_email):
            raise RuntimeError("Bootstrap admin e-mail already in use")
        await db.hub_users.insert_one({
            "email": admin_email, "password_hash": hash_password(admin_pw),
            "name": "Davi Braga", "role": "super_admin",
            "active": True, "token_version": 0,
            "created_at": now_utc().isoformat(),
        })
        logger.info("Seeded admin %s", admin_email)
    # Backfill user_type on existing staff users (non-destructive migration)
    await db.hub_users.update_many({"user_type": {"$exists": False}},
                                   {"$set": {"user_type": "staff"}})

    # Optional extra staff accounts (e.g. a dedicated "admin" or "viewer" role
    # account for RBAC testing/ops) — seeded ONLY when both email and password
    # are explicitly provided via environment. No hardcoded email, no hardcoded
    # or default password: if the pair of variables is absent, the account is
    # simply not created. This mirrors the ADMIN_EMAIL/ADMIN_PASSWORD bootstrap
    # above rather than baking any credential into source.
    OPTIONAL_STAFF_SEEDS = [
        {"role": "admin", "email_var": "STAFF_ADMIN_EMAIL", "password_var": "STAFF_ADMIN_PASSWORD",
         "name_var": "STAFF_ADMIN_NAME", "default_name": "Admin DACOT"},
        {"role": "viewer", "email_var": "STAFF_VIEWER_EMAIL", "password_var": "STAFF_VIEWER_PASSWORD",
         "name_var": "STAFF_VIEWER_NAME", "default_name": "Viewer DACOT"},
    ]
    for seed in OPTIONAL_STAFF_SEEDS:
        seed_email = os.environ.get(seed["email_var"], "").strip().lower()
        seed_pw = os.environ.get(seed["password_var"], "")
        if not seed_email or not seed_pw:
            continue
        seed_name = os.environ.get(seed["name_var"]) or seed["default_name"]
        ex = await db.hub_users.find_one({"email": seed_email})
        if not ex:
            if await _email_in_use(seed_email):
                raise RuntimeError("Bootstrap staff e-mail already in use")
            await db.hub_users.insert_one({
                "email": seed_email, "password_hash": hash_password(seed_pw),
                "name": seed_name, "role": seed["role"], "user_type": "staff",
                "active": True, "token_version": 0, "created_at": now_utc().isoformat(),
            })
            logger.info("Seeded staff %s (%s)", seed_email, seed["role"])
    # Seed modules
    for m in DEFAULT_MODULES:
        await db.modules.update_one({"key": m["key"]}, {"$setOnInsert": m}, upsert=True)
    await migrate_legacy_orders_launch_urls(db)

    # Non-destructive migration: tenant_users become login-capable restaurant users.
    # Maps legacy roles/metadata only. Never invent or overwrite credentials.
    ROLE_MAP = {"Proprietário": "admin", "Proprietária": "admin",
                "Gerente": "manager", "Caixa": "waiter", "Chef": "kitchen"}
    for legacy_role, role in ROLE_MAP.items():
        await db.tenant_users.update_many(
            {"role": legacy_role}, {"$set": {"role": role}},
        )
    await db.tenant_users.update_many(
        {"user_type": {"$exists": False}}, {"$set": {"user_type": "restaurant"}},
    )
    await db.tenant_users.update_many(
        {"token_version": {"$exists": False}}, {"$set": {"token_version": 0}},
    )
    await bootstrap_orders_user_grants(db, VALID_HANDOFF_ROLES, TENANT_OPERATIONAL_STATUSES)
    logger.info("Índices e migrações de startup concluídos")


app.include_router(api_router)


# API routes are registered before these frontend routes. This keeps the API
# authoritative for every /api request, including unknown paths, and prevents
# the React SPA fallback from ever masking an API error as index.html.
@app.api_route("/api", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"], include_in_schema=False)
@app.api_route("/api/{api_path:path}", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"], include_in_schema=False)
async def api_not_found(api_path: str = ""):
    raise HTTPException(status_code=404, detail="Not Found")


# CRA writes hashed JavaScript and CSS under /static. Mounting that directory
# before the SPA fallback lets real files retain their normal content type and
# cache headers. HTML and unhashed files must be revalidated so a browser never
# keeps an old document that points to an earlier frontend release.
FRONTEND_REVALIDATE_CACHE_CONTROL = "no-cache, max-age=0, must-revalidate"
FRONTEND_IMMUTABLE_CACHE_CONTROL = "public, max-age=31536000, immutable"
_FRONTEND_HASHED_ASSET = re.compile(r".+\.[0-9a-f]{8,}\.[^./]+$", re.IGNORECASE)


def frontend_asset_cache_control(asset_path: str) -> str:
    """Cache CRA content-addressed assets long; revalidate every other file."""
    filename = Path(asset_path).name
    if _FRONTEND_HASHED_ASSET.fullmatch(filename):
        return FRONTEND_IMMUTABLE_CACHE_CONTROL
    return FRONTEND_REVALIDATE_CACHE_CONTROL


class FrontendStaticFiles(StaticFiles):
    """Give cache semantics to the generated React assets mounted at /static."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers["Cache-Control"] = frontend_asset_cache_control(path)
        return response


if (FRONTEND_BUILD_DIR / "static").is_dir():
    app.mount("/static", FrontendStaticFiles(directory=FRONTEND_BUILD_DIR / "static"), name="frontend-static")


def frontend_file_or_index(requested_path: str) -> FileResponse:
    """Serve a build artifact when it exists, otherwise hand navigation to React.

    This only runs for GET/HEAD frontend routes. It deliberately rejects API
    paths so API failures remain JSON 404 responses.
    """
    if requested_path == "api" or requested_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not Found")

    index_file = FRONTEND_BUILD_DIR / "index.html"
    if not index_file.is_file():
        raise HTTPException(status_code=404, detail="Frontend build not found")

    candidate = (FRONTEND_BUILD_DIR / requested_path).resolve()
    try:
        candidate.relative_to(FRONTEND_BUILD_DIR.resolve())
    except ValueError:
        # A traversal attempt must never escape the generated frontend build.
        pass
    else:
        if candidate.is_file():
            return FileResponse(candidate, headers={
                "Cache-Control": frontend_asset_cache_control(candidate.name),
            })
    return FileResponse(index_file, headers={"Cache-Control": FRONTEND_REVALIDATE_CACHE_CONTROL})


@app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
async def serve_frontend_root():
    return frontend_file_or_index("")


@app.api_route("/{frontend_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
async def serve_frontend(frontend_path: str):
    return frontend_file_or_index(frontend_path)


app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=[FRONTEND_URL, "http://localhost:3000"],
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Module-Key", TAB_SESSION_HEADER],
)


@app.on_event("shutdown")
async def shutdown():
    client.close()
