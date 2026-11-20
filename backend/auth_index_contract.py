"""Contract shared by the Hub startup check and the explicit index migration.

The contract intentionally indexes only string identifiers.  WhatsApp-only
owners omit ``email`` entirely, so a conventional unique ``email_1`` index is
not compatible with the onboarding model.
"""

from typing import Any, Iterable


EMAIL_INDEX_NAME = "tenant_users_email_unique"
PHONE_INDEX_NAME = "tenant_users_confirmed_phone_unique"

EMAIL_PARTIAL_FILTER = {"email": {"$type": "string"}}
PHONE_PARTIAL_FILTER = {"phone_number": {"$type": "string"}}


def has_single_key(index: dict[str, Any], field: str) -> bool:
    """Return whether an index has exactly the expected ascending key."""
    key = index.get("key") or {}
    return list(key.items()) == [(field, 1)]


def matches_identifier_index(
    index: dict[str, Any], *, field: str, partial_filter: dict[str, Any]
) -> bool:
    return (
        has_single_key(index, field)
        and index.get("unique") is True
        and index.get("partialFilterExpression") == partial_filter
    )


def incompatible_identifier_indexes(
    indexes: Iterable[dict[str, Any]], *, field: str, partial_filter: dict[str, Any]
) -> list[dict[str, Any]]:
    """Find same-key indexes that would still impose incompatible semantics."""
    return [
        index for index in indexes
        if has_single_key(index, field)
        and not matches_identifier_index(index, field=field, partial_filter=partial_filter)
    ]


def identifier_index_errors(indexes: Iterable[dict[str, Any]]) -> list[str]:
    """Return safe, non-data-bearing contract failures for startup diagnostics."""
    indexes = list(indexes)
    errors: list[str] = []
    for field, partial_filter in (
        ("email", EMAIL_PARTIAL_FILTER),
        ("phone_number", PHONE_PARTIAL_FILTER),
    ):
        compatible = [
            index for index in indexes
            if matches_identifier_index(index, field=field, partial_filter=partial_filter)
        ]
        incompatible = incompatible_identifier_indexes(
            indexes, field=field, partial_filter=partial_filter
        )
        if not compatible:
            errors.append(f"{field}_partial_unique_missing")
        if incompatible:
            errors.append(f"{field}_index_incompatible")
    return errors
