"""Safe, one-time-compatible launch URL migration for the Pedidos module."""

ORDERS_LEGACY_LAUNCH_ORIGIN = "https://pedidos.dacot.app"
ORDERS_LAUNCH_ORIGIN = "https://dacot-pedidos-frontend.onrender.com"
ORDERS_LAUNCH_URL_TEMPLATE = f"{ORDERS_LAUNCH_ORIGIN}/{{slug}}"
_LEGACY_ORDERS_LAUNCH_URL_REGEX = r"^https://pedidos\.dacot\.app(?:/|$)"


async def migrate_legacy_orders_launch_urls(db) -> None:
    """Replace only the retired Pedidos origin in catalog and tenant overrides.

    Each write is conditional on the exact legacy value, so repeated startups are
    harmless. Tenant overrides using any other (including custom) origin remain
    untouched.
    """
    await db.modules.update_one(
        {
            "key": "orders",
            "launch_url_template": f"{ORDERS_LEGACY_LAUNCH_ORIGIN}/{{slug}}",
        },
        {"$set": {"launch_url_template": ORDERS_LAUNCH_URL_TEMPLATE}},
    )

    legacy_overrides = db.tenant_modules.find(
        {
            "module_key": "orders",
            "launch_url": {"$regex": _LEGACY_ORDERS_LAUNCH_URL_REGEX},
        },
        {"_id": 1, "launch_url": 1},
    )
    async for override in legacy_overrides:
        legacy_url = override["launch_url"]
        migrated_url = ORDERS_LAUNCH_ORIGIN + legacy_url[len(ORDERS_LEGACY_LAUNCH_ORIGIN):]
        await db.tenant_modules.update_one(
            {"_id": override["_id"], "launch_url": legacy_url},
            {"$set": {"launch_url": migrated_url}},
        )
