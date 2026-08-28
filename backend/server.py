from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

import os
import logging
import secrets
import hashlib
from datetime import datetime, timezone, timedelta
from html import escape
from typing import List, Optional, Annotated, Any
from urllib.parse import urlparse

import bcrypt
import jwt
import httpx
from bson import ObjectId
from fastapi import FastAPI, APIRouter, HTTPException, Depends, Request, Response, BackgroundTasks
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field, EmailStr, BeforeValidator, ConfigDict

# ─── Setup ─────────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("dacot-hub")

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]

JWT_ALGORITHM = "HS256"
JWT_SECRET = os.environ["JWT_SECRET"]
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:3000")
EMAIL_BASE_URL = (os.environ.get("INTEGRATION_PROXY_URL") or "").strip().rstrip("/") or "https://integrations.emergentagent.com"
EMAIL_KEY = os.environ.get("EMERGENT_EMAIL_KEY", "")
EMAIL_FROM_NAME = os.environ.get("EMAIL_FROM_NAME") or "DACOT Hub"

app = FastAPI(title="DACOT Hub API")
api_router = APIRouter(prefix="/api")

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


def create_access_token(user_id: str, email: str, ver: int = 0) -> str:
    payload = {"sub": user_id, "email": email, "ver": ver,
               "exp": now_utc() + timedelta(minutes=60), "type": "access"}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: str, ver: int = 0) -> str:
    payload = {"sub": user_id, "ver": ver,
               "exp": now_utc() + timedelta(days=7), "type": "refresh"}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _set_auth_cookies(response: Response, access: str, refresh: str) -> None:
    response.set_cookie("access_token", access, httponly=True, secure=True,
                        samesite="none", max_age=3600, path="/")
    response.set_cookie("refresh_token", refresh, httponly=True, secure=True,
                        samesite="none", max_age=604800, path="/")


async def get_current_user(request: Request) -> dict:
    token = request.cookies.get("access_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    if not token:
        raise HTTPException(401, "Não autenticado")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            raise HTTPException(401, "Token inválido")
        user = await db.hub_users.find_one({"_id": ObjectId(payload["sub"])})
        if not user or not user.get("active", True):
            raise HTTPException(401, "Usuário não encontrado")
        if payload.get("ver", 0) != user.get("token_version", 0):
            raise HTTPException(401, "Sessão expirada")
        user["_id"] = str(user["_id"])
        user.pop("password_hash", None)
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expirado")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Token inválido")


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
async def send_password_reset_email(to_email: str, token: str) -> bool:
    base = FRONTEND_URL.rstrip("/")
    link = f"{base}/reset-password?token={token}"
    if not EMAIL_KEY or EMAIL_KEY.startswith("{") or not base.startswith("https://"):
        if urlparse(base).hostname in ("localhost", "127.0.0.1", "::1"):
            logger.warning("Email not configured; reset link: %s", link)
        else:
            logger.error("Password reset email not configured")
        return False
    brand = escape(EMAIL_FROM_NAME)
    html = (
        f'<table role="presentation" width="100%"><tr><td style="padding:24px;font-family:Arial,sans-serif">'
        f'<p>Recebemos uma solicitação para redefinir sua senha no {brand}.</p>'
        f'<p><a href="{escape(link)}">Redefinir minha senha</a></p>'
        f'<p>Este link expira em 1 hora e pode ser usado apenas uma vez. Se você não solicitou, ignore este e-mail.</p>'
        f'<p style="font-size:12px;color:#888">Enviado por {brand}.</p>'
        f'</td></tr></table>'
    )
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(f"{EMAIL_BASE_URL}/api/v1/email/send",
                             headers={"X-Email-Key": EMAIL_KEY},
                             json={"to": [to_email],
                                   "subject": f"Redefina sua senha do {EMAIL_FROM_NAME}",
                                   "html": html, "from_name": EMAIL_FROM_NAME})
        r.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"reset email failed: {e}")
        return False


# ─── Auth Models ───────────────────────────────────────────────────────────────
class LoginIn(BaseModel):
    email: EmailStr
    password: str

class ForgotIn(BaseModel):
    email: EmailStr

class ResetIn(BaseModel):
    token: str
    password: str = Field(min_length=6)


# ─── Auth endpoints ────────────────────────────────────────────────────────────
@api_router.post("/auth/login")
async def login(payload: LoginIn, request: Request, response: Response):
    email = payload.email.lower()
    ip = request.client.host if request.client else "unknown"
    await _check_lockout(ip, email)
    user = await db.hub_users.find_one({"email": email})
    if not user or not verify_password(payload.password, user["password_hash"]) or not user.get("active", True):
        await _record_attempt(ip, email, False)
        raise HTTPException(401, "E-mail ou senha inválidos")
    await db.login_attempts.delete_many({"email": email})
    await db.hub_users.update_one({"_id": user["_id"]}, {"$set": {"last_login_at": now_utc().isoformat()}})
    uid = str(user["_id"])
    ver = user.get("token_version", 0)
    access = create_access_token(uid, email, ver)
    refresh = create_refresh_token(uid, ver)
    _set_auth_cookies(response, access, refresh)
    await log_activity(actor_id=uid, actor_name=user.get("name", email),
                       action="hub_user.login", target_type="hub_user", target_id=uid)
    return {"id": uid, "email": email, "name": user.get("name"), "role": user.get("role", "admin")}


@api_router.post("/auth/logout")
async def logout(response: Response, _u: dict = Depends(get_current_user)):
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")
    return {"ok": True}


@api_router.get("/auth/me")
async def me(user: dict = Depends(get_current_user)):
    return {"id": user["_id"], "email": user["email"], "name": user.get("name"),
            "role": user.get("role", "admin")}


@api_router.post("/auth/refresh")
async def refresh(request: Request, response: Response):
    tok = request.cookies.get("refresh_token")
    if not tok:
        raise HTTPException(401, "Sem refresh token")
    try:
        payload = jwt.decode(tok, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "refresh":
            raise HTTPException(401, "Token inválido")
        user = await db.hub_users.find_one({"_id": ObjectId(payload["sub"])})
        if not user or payload.get("ver", 0) != user.get("token_version", 0):
            raise HTTPException(401, "Sessão expirada")
        access = create_access_token(str(user["_id"]), user["email"], user.get("token_version", 0))
        response.set_cookie("access_token", access, httponly=True, secure=True,
                            samesite="none", max_age=3600, path="/")
        return {"ok": True}
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Token inválido")


GENERIC_RESET_RESPONSE = {"message": "Se este e-mail estiver cadastrado, um link de redefinição foi enviado."}


@api_router.post("/auth/forgot-password")
async def forgot(payload: ForgotIn, background_tasks: BackgroundTasks):
    email = payload.email.lower()
    since = now_utc() - timedelta(minutes=15)
    cnt = await db.password_reset_requests.count_documents({"email": email, "created_at": {"$gt": since.isoformat()}})
    await db.password_reset_requests.insert_one({"email": email, "created_at": now_utc().isoformat()})
    if cnt >= 5:
        return GENERIC_RESET_RESPONSE
    user = await db.hub_users.find_one({"email": email})
    if not user:
        return GENERIC_RESET_RESPONSE
    raw = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw.encode()).hexdigest()
    await db.password_reset_tokens.insert_one({
        "token_hash": token_hash, "user_id": str(user["_id"]), "email": email,
        "used": False, "expires_at": now_utc() + timedelta(hours=1),
        "created_at": now_utc(),
    })
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
    await db.hub_users.update_one(
        {"_id": ObjectId(doc["user_id"])},
        {"$set": {"password_hash": hash_password(payload.password)}, "$inc": {"token_version": 1}},
    )
    await db.password_reset_tokens.delete_many({"user_id": doc["user_id"], "used": False})
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
    status: str = "trial"
    address: Optional[str] = ""
    notes: Optional[str] = ""

class TenantPatch(BaseModel):
    name: Optional[str] = None
    owner_name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    status: Optional[str] = None
    address: Optional[str] = None
    notes: Optional[str] = None


VALID_STATUS = {"active", "trial", "suspended", "inactive"}


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
        "status": doc.get("status", "trial"),
        "address": doc.get("address", ""),
        "notes": doc.get("notes", ""),
        "created_at": doc.get("created_at"),
    }


# ─── Tenants ───────────────────────────────────────────────────────────────────
@api_router.get("/hub/tenants")
async def list_tenants(status: Optional[str] = None, q: Optional[str] = None,
                       _u: dict = Depends(get_current_user)):
    query: dict = {}
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
        users = await db.tenant_users.count_documents({"tenant_id": tid})
        base["active_modules"] = active_mods
        base["users_count"] = users
        out.append(base)
    return out


@api_router.post("/hub/tenants")
async def create_tenant(payload: TenantIn, user: dict = Depends(get_current_user)):
    if payload.status not in VALID_STATUS:
        raise HTTPException(400, "Status inválido")
    doc = {
        "name": payload.name.strip(),
        "slug": _slug(payload.name),
        "owner_name": payload.owner_name.strip(),
        "email": payload.email.lower(),
        "phone": payload.phone or "",
        "status": payload.status,
        "address": payload.address or "",
        "notes": payload.notes or "",
        "created_at": now_utc().isoformat(),
        "updated_at": now_utc().isoformat(),
    }
    res = await db.tenants.insert_one(doc)
    tid = str(res.inserted_id)
    await log_activity(actor_id=user["_id"], actor_name=user.get("name", user["email"]),
                       action="tenant.created", target_type="tenant", target_id=tid,
                       tenant_id=tid, metadata={"name": doc["name"]})
    doc["_id"] = res.inserted_id
    return {**_tenant_out(doc), "active_modules": 0, "users_count": 0}


@api_router.get("/hub/tenants/{tid}")
async def get_tenant(tid: str, _u: dict = Depends(get_current_user)):
    if not ObjectId.is_valid(tid):
        raise HTTPException(404, "Cliente não encontrado")
    d = await db.tenants.find_one({"_id": ObjectId(tid)})
    if not d:
        raise HTTPException(404, "Cliente não encontrado")
    base = _tenant_out(d)
    base["active_modules"] = await db.tenant_modules.count_documents({"tenant_id": tid, "active": True})
    base["users_count"] = await db.tenant_users.count_documents({"tenant_id": tid})
    return base


@api_router.patch("/hub/tenants/{tid}")
async def patch_tenant(tid: str, payload: TenantPatch, user: dict = Depends(get_current_user)):
    if not ObjectId.is_valid(tid):
        raise HTTPException(404, "Cliente não encontrado")
    update = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    if "email" in update:
        update["email"] = update["email"].lower()
    if "status" in update and update["status"] not in VALID_STATUS:
        raise HTTPException(400, "Status inválido")
    if "name" in update:
        update["slug"] = _slug(update["name"])
    update["updated_at"] = now_utc().isoformat()
    r = await db.tenants.update_one({"_id": ObjectId(tid)}, {"$set": update})
    if r.matched_count == 0:
        raise HTTPException(404, "Cliente não encontrado")
    if "status" in update:
        await log_activity(actor_id=user["_id"], actor_name=user.get("name", user["email"]),
                           action="tenant.status_changed", target_type="tenant",
                           target_id=tid, tenant_id=tid, metadata={"status": update["status"]})
    d = await db.tenants.find_one({"_id": ObjectId(tid)})
    return _tenant_out(d)


@api_router.delete("/hub/tenants/{tid}")
async def delete_tenant(tid: str, user: dict = Depends(get_current_user)):
    if not ObjectId.is_valid(tid):
        raise HTTPException(404, "Cliente não encontrado")
    r = await db.tenants.delete_one({"_id": ObjectId(tid)})
    if r.deleted_count == 0:
        raise HTTPException(404, "Cliente não encontrado")
    await db.tenant_modules.delete_many({"tenant_id": tid})
    await db.tenant_users.delete_many({"tenant_id": tid})
    await log_activity(actor_id=user["_id"], actor_name=user.get("name", user["email"]),
                       action="tenant.deleted", target_type="tenant", target_id=tid)
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
async def list_modules(_u: dict = Depends(get_current_user)):
    docs = await db.modules.find({}).to_list(200)
    return [_module_out(m) for m in docs]


# ─── Tenant modules (activation) ───────────────────────────────────────────────
class LaunchUrlIn(BaseModel):
    launch_url: str


@api_router.get("/hub/tenants/{tid}/modules")
async def tenant_modules(tid: str, _u: dict = Depends(get_current_user)):
    if not ObjectId.is_valid(tid):
        raise HTTPException(404, "Cliente não encontrado")
    tenant = await db.tenants.find_one({"_id": ObjectId(tid)})
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
async def activate_module(tid: str, mkey: str, user: dict = Depends(get_current_user)):
    if not ObjectId.is_valid(tid):
        raise HTTPException(404, "Cliente não encontrado")
    tenant = await db.tenants.find_one({"_id": ObjectId(tid)})
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
    await log_activity(actor_id=user["_id"], actor_name=user.get("name", user["email"]),
                       action="module.activated", target_type="module", target_id=mkey,
                       tenant_id=tid, metadata={"tenant_name": tenant["name"], "module": m["name"]})
    return {"ok": True}


@api_router.post("/hub/tenants/{tid}/modules/{mkey}/deactivate")
async def deactivate_module(tid: str, mkey: str, user: dict = Depends(get_current_user)):
    if not ObjectId.is_valid(tid):
        raise HTTPException(404, "Cliente não encontrado")
    tenant = await db.tenants.find_one({"_id": ObjectId(tid)})
    if not tenant:
        raise HTTPException(404, "Cliente não encontrado")
    m = await db.modules.find_one({"key": mkey})
    if not m:
        raise HTTPException(404, "Módulo não encontrado")
    await db.tenant_modules.update_one(
        {"tenant_id": tid, "module_key": mkey},
        {"$set": {"active": False, "deactivated_at": now_utc().isoformat()}},
    )
    await log_activity(actor_id=user["_id"], actor_name=user.get("name", user["email"]),
                       action="module.deactivated", target_type="module", target_id=mkey,
                       tenant_id=tid, metadata={"tenant_name": tenant["name"], "module": m["name"]})
    return {"ok": True}


@api_router.patch("/hub/tenants/{tid}/modules/{mkey}")
async def set_launch_url(tid: str, mkey: str, payload: LaunchUrlIn, _u: dict = Depends(get_current_user)):
    if not ObjectId.is_valid(tid):
        raise HTTPException(404, "Cliente não encontrado")
    await db.tenant_modules.update_one(
        {"tenant_id": tid, "module_key": mkey},
        {"$set": {"launch_url": payload.launch_url.strip()}},
        upsert=True,
    )
    return {"ok": True}


# ─── Tenant users ──────────────────────────────────────────────────────────────
@api_router.get("/hub/tenants/{tid}/users")
async def tenant_users(tid: str, _u: dict = Depends(get_current_user)):
    if not ObjectId.is_valid(tid):
        raise HTTPException(404, "Cliente não encontrado")
    docs = await db.tenant_users.find({"tenant_id": tid}).sort("created_at", -1).to_list(500)
    return [{
        "id": str(d["_id"]), "name": d.get("name", ""), "email": d.get("email", ""),
        "role": d.get("role", ""), "status": d.get("status", "active"),
        "created_at": d.get("created_at"),
    } for d in docs]


# ─── Dashboard ─────────────────────────────────────────────────────────────────
@api_router.get("/hub/dashboard/stats")
async def dashboard_stats(_u: dict = Depends(get_current_user)):
    active = await db.tenants.count_documents({"status": "active"})
    trial = await db.tenants.count_documents({"status": "trial"})
    suspended = await db.tenants.count_documents({"status": "suspended"})
    inactive = await db.tenants.count_documents({"status": "inactive"})
    total = await db.tenants.count_documents({})
    active_mods = await db.tenant_modules.count_documents({"active": True})
    total_users = await db.tenant_users.count_documents({})
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
async def dashboard_activity(limit: int = 15, _u: dict = Depends(get_current_user)):
    docs = await db.activity_log.find({}).sort("created_at", -1).limit(limit).to_list(limit)
    return [{
        "id": str(d["_id"]), "actor_name": d.get("actor_name", ""),
        "action": d.get("action", ""), "target_type": d.get("target_type", ""),
        "target_id": d.get("target_id"), "tenant_id": d.get("tenant_id"),
        "metadata": d.get("metadata", {}), "created_at": d.get("created_at"),
    } for d in docs]


# ─── Health ────────────────────────────────────────────────────────────────────
@api_router.get("/")
async def root():
    return {"service": "DACOT Hub API", "ok": True}


# ─── Startup: indexes + seed ───────────────────────────────────────────────────
DEFAULT_MODULES = [
    {"key": "orders", "name": "Pedidos", "status": "available", "icon": "clipboard-list",
     "category": "Operacional",
     "description": "Sistema para criação, acompanhamento e gerenciamento de pedidos do restaurante.",
     "launch_url_template": "https://pedidos.dacot.app/{slug}"},
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

SEED_TENANTS = [
    {"name": "Hamburgueria Exemplo", "owner_name": "João Silva", "email": "contato@hamburgueriaexemplo.com",
     "phone": "(11) 99999-0001", "status": "active", "address": "Rua das Flores, 123 — São Paulo/SP",
     "notes": "Cliente âncora — participa do programa beta.",
     "modules": ["orders", "kitchen"],
     "users": [
         {"name": "João Silva", "email": "joao@hamburgueriaexemplo.com", "role": "Proprietário", "status": "active"},
         {"name": "Marina Costa", "email": "marina@hamburgueriaexemplo.com", "role": "Gerente", "status": "active"},
         {"name": "Pedro Alves", "email": "pedro@hamburgueriaexemplo.com", "role": "Caixa", "status": "active"},
     ]},
    {"name": "Cantina Bella Napoli", "owner_name": "Giulia Rossi", "email": "giulia@bellanapoli.com.br",
     "phone": "(11) 98888-2222", "status": "active", "address": "Av. Paulista, 900 — São Paulo/SP",
     "notes": "Restaurante italiano tradicional.",
     "modules": ["orders", "kitchen"],
     "users": [
         {"name": "Giulia Rossi", "email": "giulia@bellanapoli.com.br", "role": "Proprietária", "status": "active"},
         {"name": "Marco Bianchi", "email": "marco@bellanapoli.com.br", "role": "Chef", "status": "active"},
     ]},
    {"name": "Sushi Zen", "owner_name": "Haruki Tanaka", "email": "haruki@sushizen.com.br",
     "phone": "(21) 97777-3333", "status": "trial", "address": "Rua Barata Ribeiro, 45 — Rio de Janeiro/RJ",
     "notes": "Teste iniciado em fev/2026. Interessados em Pedidos + Delivery futuramente.",
     "modules": ["orders"],
     "users": [
         {"name": "Haruki Tanaka", "email": "haruki@sushizen.com.br", "role": "Proprietário", "status": "active"},
     ]},
    {"name": "Padaria Grão Dourado", "owner_name": "Ana Ferreira", "email": "ana@graodourado.com.br",
     "phone": "(31) 96666-4444", "status": "trial", "address": "Rua da Bahia, 210 — Belo Horizonte/MG",
     "notes": "Onboarding em andamento.", "modules": [], "users": []},
    {"name": "Boteco do Zé", "owner_name": "José Pereira", "email": "ze@botecodoze.com",
     "phone": "(11) 95555-5555", "status": "suspended", "address": "Rua Aurora, 88 — São Paulo/SP",
     "notes": "Suspenso por inadimplência (dez/2025).", "modules": [], "users": []},
]


@app.on_event("startup")
async def startup():
    await db.hub_users.create_index("email", unique=True)
    await db.tenants.create_index("email")
    await db.tenants.create_index("slug", unique=True)
    await db.modules.create_index("key", unique=True)
    await db.tenant_modules.create_index([("tenant_id", 1), ("module_key", 1)], unique=True)
    await db.tenant_users.create_index("tenant_id")
    await db.activity_log.create_index([("created_at", -1)])
    await db.login_attempts.create_index("email")
    await db.login_attempts.create_index("identifier")
    await db.password_reset_tokens.create_index("token_hash", unique=True)
    await db.password_reset_tokens.create_index("expires_at", expireAfterSeconds=0)
    await db.password_reset_requests.create_index("email")
    await db.password_reset_requests.create_index("created_at", expireAfterSeconds=900)

    # Seed admin
    admin_email = os.environ["ADMIN_EMAIL"].lower()
    admin_pw = os.environ["ADMIN_PASSWORD"]
    existing = await db.hub_users.find_one({"email": admin_email})
    if not existing:
        await db.hub_users.insert_one({
            "email": admin_email, "password_hash": hash_password(admin_pw),
            "name": "Davi Braga", "role": "super_admin",
            "active": True, "token_version": 0,
            "created_at": now_utc().isoformat(),
        })
        logger.info("Seeded admin %s", admin_email)
    elif not verify_password(admin_pw, existing["password_hash"]):
        await db.hub_users.update_one({"email": admin_email},
                                      {"$set": {"password_hash": hash_password(admin_pw)}})

    # Seed modules
    for m in DEFAULT_MODULES:
        await db.modules.update_one({"key": m["key"]}, {"$setOnInsert": m}, upsert=True)

    # Seed tenants (only if none exists)
    tenants_count = await db.tenants.count_documents({})
    if tenants_count == 0:
        admin = await db.hub_users.find_one({"email": admin_email})
        admin_id = str(admin["_id"]) if admin else "system"
        admin_name = admin.get("name") if admin else "system"
        for t in SEED_TENANTS:
            doc = {
                "name": t["name"], "slug": _slug(t["name"]),
                "owner_name": t["owner_name"], "email": t["email"].lower(),
                "phone": t["phone"], "status": t["status"],
                "address": t["address"], "notes": t["notes"],
                "created_at": now_utc().isoformat(), "updated_at": now_utc().isoformat(),
            }
            r = await db.tenants.insert_one(doc)
            tid = str(r.inserted_id)
            for mkey in t["modules"]:
                m = await db.modules.find_one({"key": mkey})
                if m:
                    await db.tenant_modules.insert_one({
                        "tenant_id": tid, "module_key": mkey, "module_id": str(m["_id"]),
                        "active": True, "activated_at": now_utc().isoformat(),
                        "activated_by": admin_id,
                    })
            for u in t["users"]:
                await db.tenant_users.insert_one({
                    "tenant_id": tid, "name": u["name"], "email": u["email"],
                    "role": u["role"], "status": u["status"],
                    "created_at": now_utc().isoformat(),
                })
            await log_activity(actor_id=admin_id, actor_name=admin_name,
                               action="tenant.created", target_type="tenant",
                               target_id=tid, tenant_id=tid,
                               metadata={"name": t["name"], "seed": True})
        logger.info("Seeded %d tenants", len(SEED_TENANTS))


app.include_router(api_router)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=[FRONTEND_URL, "http://localhost:3000"],
    allow_methods=["*"], allow_headers=["*"],
)


@app.on_event("shutdown")
async def shutdown():
    client.close()
