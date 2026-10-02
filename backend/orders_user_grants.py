"""One-time bootstrap and constants for tenant-scoped Pedidos user grants."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from bson import ObjectId
from pymongo import ReturnDocument


ORDERS_MODULE_KEY = "orders"
ORDERS_GRANTS_BOOTSTRAP_ID = "orders_user_grants_v1"
ORDERS_GRANTS_BOOTSTRAP_LEASE_SECONDS = 15 * 60


async def bootstrap_orders_user_grants(db, valid_roles: set[str], operational_statuses: set[str]) -> None:
    """Create initial grants once, without ever re-granting later revocations."""
    await db.module_user_grants.create_index(
        [("tenant_id", 1), ("user_id", 1), ("module_key", 1)], unique=True,
    )
    now = datetime.now(timezone.utc)
    await db.module_access_migrations.update_one(
        {"_id": ORDERS_GRANTS_BOOTSTRAP_ID},
        {"$setOnInsert": {"state": "pending", "created_at": now.isoformat()}},
        upsert=True,
    )
    lock = str(uuid4())
    marker = await db.module_access_migrations.find_one_and_update(
        {
            "_id": ORDERS_GRANTS_BOOTSTRAP_ID,
            "$or": [
                {"state": {"$in": ["pending", "failed"]}},
                {"state": "running", "lease_expires_at": {"$lte": now}},
            ],
        },
        {"$set": {
            "state": "running", "lock": lock, "started_at": now.isoformat(),
            "lease_expires_at": now + timedelta(seconds=ORDERS_GRANTS_BOOTSTRAP_LEASE_SECONDS),
        }},
        return_document=ReturnDocument.AFTER,
    )
    if not marker:
        current = await db.module_access_migrations.find_one({"_id": ORDERS_GRANTS_BOOTSTRAP_ID})
        if current and current.get("state") == "completed":
            return
        raise RuntimeError("Bootstrap de grants do módulo Pedidos está em execução com lease válido")

    try:
        created = 0
        async for activation in db.tenant_modules.find({"module_key": ORDERS_MODULE_KEY, "active": True}):
            tenant_id = activation.get("tenant_id")
            if not ObjectId.is_valid(tenant_id):
                continue
            tenant = await db.tenants.find_one({"_id": ObjectId(tenant_id)})
            if not tenant or tenant.get("status", "trial") not in operational_statuses:
                continue
            async for user in db.tenant_users.find({"tenant_id": tenant_id}):
                if (user.get("status", "active") != "active" or user.get("password_reset_required")
                        or not user.get("password_hash") or user.get("role") not in valid_roles):
                    continue
                result = await db.module_user_grants.update_one(
                    {"tenant_id": tenant_id, "user_id": str(user["_id"]), "module_key": ORDERS_MODULE_KEY},
                    {"$setOnInsert": {
                        "active": True, "source": "bootstrap_v1",
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    }},
                    upsert=True,
                )
                created += result.upserted_id is not None
        await db.module_access_migrations.update_one(
            {"_id": ORDERS_GRANTS_BOOTSTRAP_ID, "lock": lock},
            {"$set": {"state": "completed", "completed_at": datetime.now(timezone.utc).isoformat(), "created_grants": created},
             "$unset": {"lock": "", "lease_expires_at": ""}},
        )
    except Exception:
        await db.module_access_migrations.update_one(
            {"_id": ORDERS_GRANTS_BOOTSTRAP_ID, "lock": lock},
            {"$set": {"state": "failed", "failed_at": datetime.now(timezone.utc).isoformat()},
             "$unset": {"lock": "", "lease_expires_at": ""}},
        )
        raise
