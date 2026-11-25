"""Explicit, guarded migration for Hub owner identifier indexes.

This program is deliberately *not* called by FastAPI startup.  Run ``--check``
first.  An operator may run ``--apply`` only during a maintenance window and
must supply a writable backup file for the previous index specifications.
No document values are printed or copied by this utility.
"""

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import secrets
import sys
from typing import Any

from pymongo import MongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError

from auth_index_contract import (
    EMAIL_INDEX_NAME,
    EMAIL_PARTIAL_FILTER,
    PHONE_INDEX_NAME,
    PHONE_PARTIAL_FILTER,
    has_single_key,
    identifier_index_errors,
    incompatible_identifier_indexes,
    matches_identifier_index,
)


LOCK_ID = "auth-identifier-indexes-v1"
LOCK_COLLECTION = "schema_migration_locks"
LOCK_TTL = timedelta(minutes=15)
APPLY_CONFIRMATION = "MIGRATE_AUTH_IDENTIFIER_INDEXES"


class MigrationError(RuntimeError):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _duplicate_string_count(collection: Any, field: str) -> int:
    """Count conflict groups without returning the underlying identifiers."""
    result = list(collection.aggregate([
        {"$match": {field: {"$type": "string"}}},
        {"$group": {"_id": f"${field}", "count": {"$sum": 1}}},
        {"$match": {"count": {"$gt": 1}}},
        {"$count": "total"},
    ]))
    return int(result[0]["total"]) if result else 0


def _index_snapshot(index: dict[str, Any]) -> dict[str, Any]:
    """Return a createIndexes-compatible, non-data-bearing specification."""
    allowed = (
        "name", "key", "unique", "sparse", "partialFilterExpression",
        "collation", "expireAfterSeconds", "hidden",
    )
    snapshot = {name: index[name] for name in allowed if name in index}
    if "key" in snapshot:
        snapshot["key"] = dict(snapshot["key"])
    return snapshot


def _write_backup(path: Path, indexes: list[dict[str, Any]]) -> None:
    if path.exists():
        raise MigrationError("O arquivo de backup já existe; escolha um novo caminho")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "dacot-hub-auth-index-backup-v1",
        "created_at": _utcnow().isoformat(),
        "indexes": [_index_snapshot(index) for index in indexes],
    }
    with path.open("x", encoding="utf-8") as backup:
        json.dump(payload, backup, ensure_ascii=False, indent=2, default=str)


def inspect(collection: Any) -> dict[str, Any]:
    indexes = list(collection.list_indexes())
    email_indexes = [index for index in indexes if has_single_key(index, "email")]
    phone_indexes = [index for index in indexes if has_single_key(index, "phone_number")]
    return {
        "contract_errors": identifier_index_errors(indexes),
        "email_index_count": len(email_indexes),
        "phone_index_count": len(phone_indexes),
        "duplicate_string_emails": _duplicate_string_count(collection, "email"),
        "duplicate_string_phone_numbers": _duplicate_string_count(collection, "phone_number"),
        # Arrays can make an index multikey. They are rejected instead of being
        # silently indexed with potentially surprising uniqueness semantics.
        "email_array_documents": collection.count_documents({"email": {"$type": "array"}}),
        "phone_number_array_documents": collection.count_documents({"phone_number": {"$type": "array"}}),
    }


def _require_migratable(indexes: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, bool]:
    """Allow only the known legacy e-mail shape; fail closed for surprises."""
    email_indexes = [index for index in indexes if has_single_key(index, "email")]
    phone_indexes = [index for index in indexes if has_single_key(index, "phone_number")]
    incompatible_email = incompatible_identifier_indexes(
        indexes, field="email", partial_filter=EMAIL_PARTIAL_FILTER
    )
    incompatible_phone = incompatible_identifier_indexes(
        indexes, field="phone_number", partial_filter=PHONE_PARTIAL_FILTER
    )
    if len(email_indexes) > 1 or len(phone_indexes) > 1:
        raise MigrationError("Há múltiplos índices de identificador; revisão manual obrigatória")
    if incompatible_phone:
        raise MigrationError("Índice phone_number incompatível; revisão manual obrigatória")
    legacy_email = incompatible_email[0] if incompatible_email else None
    if legacy_email and not (
        legacy_email.get("unique") is True
        and not legacy_email.get("partialFilterExpression")
        and not legacy_email.get("sparse")
    ):
        raise MigrationError("Índice email incompatível fora do formato legado conhecido")
    email_ready = any(
        matches_identifier_index(index, field="email", partial_filter=EMAIL_PARTIAL_FILTER)
        for index in email_indexes
    )
    return legacy_email, email_ready


def _acquire_lock(database: Any, owner: str) -> None:
    now = _utcnow()
    try:
        record = database[LOCK_COLLECTION].find_one_and_update(
            {"_id": LOCK_ID, "$or": [{"expires_at": {"$lte": now}}, {"owner": owner}]},
            {"$set": {"owner": owner, "expires_at": now + LOCK_TTL, "updated_at": now},
             "$setOnInsert": {"created_at": now}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
    except DuplicateKeyError as exc:
        raise MigrationError("Outra migração de índices está em andamento") from exc
    if not record or record.get("owner") != owner:
        raise MigrationError("Outra migração de índices está em andamento")


def _release_lock(database: Any, owner: str) -> None:
    database[LOCK_COLLECTION].delete_one({"_id": LOCK_ID, "owner": owner})


def apply(database: Any, backup_file: Path) -> dict[str, Any]:
    """Perform a guarded migration; used by the CLI and disposable-Mongo tests."""
    collection = database.tenant_users
    owner = secrets.token_urlsafe(24)
    _acquire_lock(database, owner)
    created_email = False
    created_phone = False
    dropped_legacy: dict[str, Any] | None = None
    try:
        # Preflight runs while holding the lock.  A second operator therefore
        # cannot invalidate its duplicate checks between validation and DDL.
        before = inspect(collection)
        blockers = {
            key: value for key, value in before.items()
            if key in {
                "duplicate_string_emails", "duplicate_string_phone_numbers",
                "email_array_documents", "phone_number_array_documents",
            } and value
        }
        if blockers:
            raise MigrationError("Pré-verificação encontrou identificadores incompatíveis")

        indexes = list(collection.list_indexes())
        legacy_email, email_ready = _require_migratable(indexes)
        phone_ready = any(
            matches_identifier_index(index, field="phone_number", partial_filter=PHONE_PARTIAL_FILTER)
            for index in indexes
        )
        if email_ready and phone_ready and not before["contract_errors"]:
            return {"state": "already_current", **before}

        _write_backup(backup_file, indexes)
        # A conventional and a partial index with the same key pattern cannot
        # safely coexist on all supported MongoDB versions.  The caller must
        # first place the API in maintenance mode; then this narrow window is
        # protected by the migration lock and validated rollback path.
        if legacy_email:
            collection.drop_index(legacy_email["name"])
            dropped_legacy = legacy_email
        if not email_ready:
            collection.create_index(
                "email", unique=True, name=EMAIL_INDEX_NAME,
                partialFilterExpression=EMAIL_PARTIAL_FILTER,
            )
            created_email = True
        if not phone_ready:
            collection.create_index(
                "phone_number", unique=True, name=PHONE_INDEX_NAME,
                partialFilterExpression=PHONE_PARTIAL_FILTER,
            )
            created_phone = True
        after = inspect(collection)
        if after["contract_errors"]:
            raise MigrationError("Validação posterior dos índices falhou")
        return {"state": "migrated", **after}
    except Exception:
        # Restore the known legacy state if a subsequent build or validation
        # fails.  This never changes application documents.
        if created_phone:
            try:
                collection.drop_index(PHONE_INDEX_NAME)
            except PyMongoError:
                pass
        if created_email:
            try:
                collection.drop_index(EMAIL_INDEX_NAME)
            except PyMongoError:
                pass
        if dropped_legacy:
            collection.create_index(
                list(dropped_legacy["key"].items()),
                **{key: value for key, value in _index_snapshot(dropped_legacy).items()
                   if key not in {"key", "name"}},
                name=dropped_legacy["name"],
            )
        raise
    finally:
        _release_lock(database, owner)


def main() -> int:
    parser = argparse.ArgumentParser(description="Migração explícita de índices de autenticação DACOT-HUB")
    parser.add_argument("--apply", action="store_true", help="executa a migração após as pré-verificações")
    parser.add_argument("--backup-file", type=Path, help="arquivo novo para backup dos metadados dos índices")
    parser.add_argument("--confirm", help=f"deve ser exatamente {APPLY_CONFIRMATION}")
    args = parser.parse_args()
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        raise MigrationError("MONGO_URL e DB_NAME são obrigatórios")
    client = MongoClient(mongo_url, serverSelectionTimeoutMS=15_000)
    try:
        database = client[db_name]
        if not args.apply:
            print(json.dumps(inspect(database.tenant_users), sort_keys=True))
            return 0
        if args.confirm != APPLY_CONFIRMATION or not args.backup_file:
            raise MigrationError("--apply exige --confirm e --backup-file")
        print(json.dumps(apply(database, args.backup_file), sort_keys=True))
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (MigrationError, PyMongoError) as exc:
        print(f"Migração de índices não executada: {exc}", file=sys.stderr)
        raise SystemExit(2)
