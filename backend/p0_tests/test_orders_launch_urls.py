import asyncio
import importlib.util
import re
from pathlib import Path

import pytest


BACKEND = Path(__file__).resolve().parents[1]


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AsyncCursor:
    def __init__(self, items):
        self.items = iter(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self.items)
        except StopIteration:
            raise StopAsyncIteration


class Collection:
    def __init__(self, documents):
        self.documents = documents

    async def update_one(self, query, update, upsert=False):
        for document in self.documents:
            if all(document.get(key) == value for key, value in query.items()):
                document.update(update["$set"])
                return

    def find(self, query, projection):
        pattern = query["launch_url"]["$regex"]
        return AsyncCursor([
            document for document in self.documents
            if document.get("module_key") == query["module_key"]
            and re.match(pattern, document.get("launch_url", ""))
        ])


class FakeDb:
    def __init__(self):
        self.modules = Collection([
            {"key": "orders", "launch_url_template": "https://pedidos.dacot.app/{slug}", "name": "Pedidos"},
            {"key": "kitchen", "launch_url_template": "https://cozinha.dacot.app/{slug}", "name": "Cozinha"},
        ])
        self.tenant_modules = Collection([
            {"_id": "legacy", "tenant_id": "tenant-a", "module_key": "orders", "launch_url": "https://pedidos.dacot.app/tenant-a", "active": True},
            {"_id": "custom", "tenant_id": "tenant-b", "module_key": "orders", "launch_url": "https://orders.example.test/tenant-b", "active": True},
            {"_id": "other-module", "tenant_id": "tenant-a", "module_key": "kitchen", "launch_url": "https://pedidos.dacot.app/tenant-a", "active": True},
        ])


def test_orders_launch_url_migration_is_idempotent_and_scoped():
    asyncio.run(_run_orders_launch_url_migration_test())


async def _run_orders_launch_url_migration_test():
    launch_urls = load("orders_launch_urls", BACKEND / "orders_launch_urls.py")
    database = FakeDb()

    await launch_urls.migrate_legacy_orders_launch_urls(database)
    await launch_urls.migrate_legacy_orders_launch_urls(database)

    orders = next(module for module in database.modules.documents if module["key"] == "orders")
    kitchen = next(module for module in database.modules.documents if module["key"] == "kitchen")
    assert orders["launch_url_template"] == launch_urls.ORDERS_LAUNCH_URL_TEMPLATE
    assert orders["name"] == "Pedidos"
    assert kitchen["launch_url_template"] == "https://cozinha.dacot.app/{slug}"

    overrides = {override["_id"]: override for override in database.tenant_modules.documents}
    assert overrides["legacy"]["launch_url"] == "https://dacot-pedidos-frontend.onrender.com/tenant-a"
    assert overrides["legacy"]["tenant_id"] == "tenant-a"
    assert overrides["legacy"]["active"] is True
    assert overrides["custom"]["launch_url"] == "https://orders.example.test/tenant-b"
    assert overrides["other-module"]["launch_url"] == "https://pedidos.dacot.app/tenant-a"


def test_orders_template_uses_render_origin_slug_and_allowlist(monkeypatch):
    launch_urls = load("orders_launch_urls_template", BACKEND / "orders_launch_urls.py")
    policy = load("handoff_policy_orders_template", BACKEND / "handoff_policy.py")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv(
        "HANDOFF_ALLOWED_ORIGINS_JSON",
        '{"orders":["https://dacot-pedidos-frontend.onrender.com"]}',
    )

    assert launch_urls.ORDERS_LAUNCH_URL_TEMPLATE.endswith("/{slug}")
    final_url = launch_urls.ORDERS_LAUNCH_URL_TEMPLATE.replace("{slug}", "restaurant-a")
    assert final_url == "https://dacot-pedidos-frontend.onrender.com/restaurant-a"
    assert policy.validate_launch_url(final_url, "orders") == final_url
    with pytest.raises(Exception) as rejected:
        policy.validate_launch_url("https://pedidos.dacot.app/restaurant-a", "orders")
    assert rejected.value.status_code == 400
