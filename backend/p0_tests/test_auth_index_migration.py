"""Disposable-Mongo coverage for the explicit authentication-index migration."""

import json

from auth_index_contract import EMAIL_INDEX_NAME, PHONE_INDEX_NAME
from migrate_auth_indexes import MigrationError, apply, inspect


def test_auth_index_migration_upgrades_known_legacy_email_index(services, tmp_path):
    collection = services.mongo["auth_index_migration_p0"].tenant_users
    collection.create_index("email", unique=True, name="email_1")

    before = inspect(collection)
    assert "email_index_incompatible" in before["contract_errors"]
    assert "phone_number_partial_unique_missing" in before["contract_errors"]

    backup = tmp_path / "auth-index-backup.json"
    result = apply(collection.database, backup)
    assert result["state"] == "migrated"
    assert result["contract_errors"] == []
    assert backup.exists()
    metadata = json.loads(backup.read_text(encoding="utf-8"))
    assert metadata["indexes"][1]["name"] == "email_1"
    names = {index["name"] for index in collection.list_indexes()}
    assert EMAIL_INDEX_NAME in names
    assert PHONE_INDEX_NAME in names
    assert apply(collection.database, tmp_path / "second-backup.json")["state"] == "already_current"


def test_auth_index_migration_refuses_duplicate_or_array_identifiers(services, tmp_path):
    collection = services.mongo["auth_index_migration_blockers_p0"].tenant_users
    collection.insert_many([
        {"phone_number": "+5511999999999"},
        {"phone_number": "+5511999999999"},
        {"email": ["legacy@example.test"]},
    ])
    report = inspect(collection)
    assert report["duplicate_string_phone_numbers"] == 1
    assert report["email_array_documents"] == 1
    try:
        apply(collection.database, tmp_path / "must-not-exist.json")
    except MigrationError as exc:
        assert "Pré-verificação" in str(exc)
    else:
        raise AssertionError("migration must refuse unsafe data")
    assert not (tmp_path / "must-not-exist.json").exists()
