"""Unit coverage for the one-time Pedidos-grants bootstrap migration."""

import asyncio
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bson import ObjectId


BACKEND = Path(__file__).resolve().parents[1]


def load_grants_module():
    spec = importlib.util.spec_from_file_location("orders_user_grants_test", BACKEND / "orders_user_grants.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Result:
    def __init__(self, upserted_id=None):
        self.upserted_id = upserted_id


class Cursor:
    def __init__(self, documents):
        self._documents = iter(documents)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._documents)
        except StopIteration:
            raise StopAsyncIteration


def matches(document, query):
    for key, value in query.items():
        if key == "$or":
            if not any(matches(document, condition) for condition in value):
                return False
            continue
        if isinstance(value, dict):
            if "$in" in value and document.get(key) not in value["$in"]:
                return False
            if "$lte" in value and (key not in document or document[key] > value["$lte"]):
                return False
            continue
        if document.get(key) != value:
            return False
    return True


class Collection:
    def __init__(self, documents=()):
        self.documents = [dict(document) for document in documents]
        self.indexes = []
        self.lock_acquisitions = 0

    async def create_index(self, keys, unique=False):
        self.indexes.append((keys, unique))

    async def find_one(self, query):
        return next((document for document in self.documents if matches(document, query)), None)

    def find(self, query):
        return Cursor([document for document in self.documents if matches(document, query)])

    async def update_one(self, query, update, upsert=False):
        document = await self.find_one(query)
        if document is None:
            if not upsert:
                return Result()
            document = dict(query)
            document.update(update.get("$setOnInsert", {}))
            self.documents.append(document)
            document.update(update.get("$set", {}))
            return Result(document.get("_id", "upserted"))
        document.update(update.get("$set", {}))
        for field in update.get("$unset", {}):
            document.pop(field, None)
        return Result()

    async def find_one_and_update(self, query, update, return_document=None):
        await asyncio.sleep(0)
        document = await self.find_one(query)
        if document is None:
            return None
        self.lock_acquisitions += 1
        document.update(update.get("$set", {}))
        return document


class FakeDb:
    def __init__(self, tenant_id, eligible_user_id, revoked_user_id, marker=()):
        self.module_user_grants = Collection([
            {"tenant_id": str(tenant_id), "user_id": str(revoked_user_id), "module_key": "orders", "active": False},
        ])
        self.module_access_migrations = Collection(marker)
        self.tenants = Collection([
            {"_id": tenant_id, "status": "active"},
        ])
        self.tenant_modules = Collection([
            {"tenant_id": str(tenant_id), "module_key": "orders", "active": True},
            {"tenant_id": str(tenant_id), "module_key": "kitchen", "active": True},
        ])
        self.tenant_users = Collection([
            {"_id": eligible_user_id, "tenant_id": str(tenant_id), "status": "active", "role": "waiter", "password_hash": "present"},
            {"_id": revoked_user_id, "tenant_id": str(tenant_id), "status": "active", "role": "admin", "password_hash": "present"},
            {"_id": ObjectId(), "tenant_id": str(tenant_id), "status": "active", "role": "waiter"},
        ])


def test_orders_grants_bootstrap_is_scoped_idempotent_and_never_regrants_revoked_user():
    asyncio.run(_run_bootstrap_test())


async def _run_bootstrap_test():
    grants = load_grants_module()
    tenant_id, eligible_user_id, revoked_user_id = ObjectId(), ObjectId(), ObjectId()
    database = FakeDb(tenant_id, eligible_user_id, revoked_user_id)

    await grants.bootstrap_orders_user_grants(database, {"admin", "waiter"}, {"active", "trial"})
    await grants.bootstrap_orders_user_grants(database, {"admin", "waiter"}, {"active", "trial"})

    records = database.module_user_grants.documents
    created = [item for item in records if item["user_id"] == str(eligible_user_id)]
    revoked = next(item for item in records if item["user_id"] == str(revoked_user_id))
    assert len(created) == 1 and created[0]["active"] is True
    assert revoked["active"] is False
    assert {item["module_key"] for item in records} == {"orders"}
    marker = database.module_access_migrations.documents[0]
    assert marker["_id"] == grants.ORDERS_GRANTS_BOOTSTRAP_ID
    assert marker["state"] == "completed"
    assert database.module_user_grants.indexes == [([("tenant_id", 1), ("user_id", 1), ("module_key", 1)], True)] * 2


def test_running_bootstrap_lease_is_fail_closed_until_it_expires():
    asyncio.run(_run_lease_recovery_test())


async def _run_lease_recovery_test():
    grants = load_grants_module()
    now = datetime.now(timezone.utc)
    tenant_id, eligible_user_id, revoked_user_id = ObjectId(), ObjectId(), ObjectId()
    database = FakeDb(tenant_id, eligible_user_id, revoked_user_id, [{
        "_id": grants.ORDERS_GRANTS_BOOTSTRAP_ID,
        "state": "running",
        "lock": "live-instance",
        "lease_expires_at": now + timedelta(minutes=1),
    }])

    try:
        await grants.bootstrap_orders_user_grants(database, {"admin", "waiter"}, {"active", "trial"})
        assert False, "a valid running lease must not be taken over"
    except RuntimeError as error:
        assert "lease válido" in str(error)
    assert database.module_access_migrations.lock_acquisitions == 0

    marker = database.module_access_migrations.documents[0]
    marker["lease_expires_at"] = now - timedelta(seconds=1)
    await asyncio.gather(
        grants.bootstrap_orders_user_grants(database, {"admin", "waiter"}, {"active", "trial"}),
        grants.bootstrap_orders_user_grants(database, {"admin", "waiter"}, {"active", "trial"}),
    )
    assert marker["state"] == "completed"
    assert database.module_access_migrations.lock_acquisitions == 1

    # Once completed, later callers — including a concurrent recovery contender
    # that arrives after the atomic acquisition — cannot run it again.
    await grants.bootstrap_orders_user_grants(database, {"admin", "waiter"}, {"active", "trial"})
    assert database.module_access_migrations.lock_acquisitions == 1
    revoked = next(item for item in database.module_user_grants.documents if item["user_id"] == str(revoked_user_id))
    assert revoked["active"] is False
