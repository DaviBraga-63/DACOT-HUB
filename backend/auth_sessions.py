"""Server-side browser sessions scoped to one browser tab.

The browser binding and tab identifier are deliberately never persisted in
plain text.  A valid session requires both values and a live database record;
neither value is an authentication credential on its own.
"""

import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional


BROWSER_COOKIE_NAME = "__Host-dacot_browser"
TAB_SESSION_HEADER = "X-DACOT-Tab-Session"
ACCESS_TTL = timedelta(minutes=60)
REFRESH_TTL = timedelta(days=7)
_TAB_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.I)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def valid_tab_session_id(value: Optional[str]) -> bool:
    return bool(value and _TAB_ID_RE.fullmatch(value))


def new_browser_binding() -> str:
    return secrets.token_urlsafe(32)


async def ensure_indexes(db) -> None:
    await db.auth_sessions.create_index(
        [("browser_binding_hash", 1), ("tab_session_id_hash", 1)], unique=True
    )
    await db.auth_sessions.create_index([("user_id", 1), ("user_type", 1)])
    await db.auth_sessions.create_index("expires_at", expireAfterSeconds=0)


def session_query(browser_binding: Optional[str], tab_session_id: Optional[str]) -> Optional[dict]:
    if not browser_binding or not valid_tab_session_id(tab_session_id):
        return None
    return {
        "browser_binding_hash": digest(browser_binding),
        "tab_session_id_hash": digest(tab_session_id),
    }


async def create_session(db, *, browser_binding: str, tab_session_id: str,
                         user_id: str, user_type: str, user_token_version: int) -> dict:
    query = session_query(browser_binding, tab_session_id)
    if not query:
        raise ValueError("invalid tab session identifier")
    now = now_utc()
    # A UUID collision is practically impossible. Replacing a previous record
    # for the exact same binding/ID still keeps the unique lookup invariant and
    # makes an explicit re-login authoritative for that tab.
    session = {
        **query,
        "user_id": user_id,
        "user_type": user_type,
        "user_token_version": user_token_version,
        "created_at": now,
        "last_seen_at": now,
        "access_expires_at": now + ACCESS_TTL,
        "refresh_expires_at": now + REFRESH_TTL,
        "expires_at": now + REFRESH_TTL,
        "revoked_at": None,
        "revocation_reason": None,
    }
    await db.auth_sessions.update_one(query, {"$set": session}, upsert=True)
    return session


async def find_session(db, *, browser_binding: Optional[str], tab_session_id: Optional[str],
                       require_access: bool) -> Optional[dict]:
    query = session_query(browser_binding, tab_session_id)
    if not query:
        return None
    now = now_utc()
    expiry_field = "access_expires_at" if require_access else "refresh_expires_at"
    session = await db.auth_sessions.find_one({
        **query,
        "revoked_at": None,
        expiry_field: {"$gt": now},
        "expires_at": {"$gt": now},
    })
    if session:
        await db.auth_sessions.update_one({"_id": session["_id"]}, {"$set": {"last_seen_at": now}})
    return session


async def refresh_session(db, *, browser_binding: Optional[str], tab_session_id: Optional[str]) -> Optional[dict]:
    session = await find_session(
        db, browser_binding=browser_binding, tab_session_id=tab_session_id, require_access=False
    )
    if not session:
        return None
    now = now_utc()
    result = await db.auth_sessions.update_one(
        {"_id": session["_id"], "revoked_at": None},
        {"$set": {"access_expires_at": now + ACCESS_TTL, "last_seen_at": now}},
    )
    if result.modified_count != 1:
        return None
    session["access_expires_at"] = now + ACCESS_TTL
    session["last_seen_at"] = now
    return session


async def revoke_session(db, *, browser_binding: Optional[str], tab_session_id: Optional[str],
                         reason: str) -> bool:
    query = session_query(browser_binding, tab_session_id)
    if not query:
        return False
    result = await db.auth_sessions.update_one(
        {**query, "revoked_at": None},
        {"$set": {"revoked_at": now_utc(), "revocation_reason": reason}},
    )
    return bool(result.modified_count)


async def revoke_user_sessions(db, *, user_id: str, user_type: str, reason: str) -> int:
    result = await db.auth_sessions.update_many(
        {"user_id": user_id, "user_type": user_type, "revoked_at": None},
        {"$set": {"revoked_at": now_utc(), "revocation_reason": reason}},
    )
    return result.modified_count
