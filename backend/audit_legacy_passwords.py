"""Explicit administrator operation. Dry-run by default; never changes passwords.

Supply MONGO_URL and DB_NAME explicitly; no .env is loaded. The historical
candidate password is entered privately, not embedded in source or CLI arguments.
"""
import argparse
import getpass
import os

import bcrypt
from pymongo import MongoClient


def inspect_accounts(db, candidate, apply=False):
    findings = []
    for user in db.tenant_users.find({}, {"password_hash": 1, "tenant_id": 1, "password_reset_required": 1}):
        hashed = user.get("password_hash")
        reason = "missing_password" if not hashed else None
        if hashed:
            try:
                if bcrypt.checkpw(candidate.encode(), hashed.encode()):
                    reason = "matches_historical_password"
            except (ValueError, TypeError):
                reason = "invalid_password_hash"
        if not reason:
            continue
        changed = False
        if apply and not user.get("password_reset_required"):
            # Compare-and-set protects a password reset occurring during the audit.
            result = db.tenant_users.update_one(
                {"_id": user["_id"], "password_hash": hashed, "password_reset_required": {"$ne": True}},
                {"$set": {"password_reset_required": True}, "$inc": {"token_version": 1}},
            )
            changed = result.modified_count == 1
        findings.append({"id": str(user["_id"]), "tenant_id": user.get("tenant_id"),
                         "reason": reason, "quarantined": changed})
    return findings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Require password recovery and revoke affected sessions")
    parser.add_argument("--confirm-db", help="Required with --apply; must exactly match DB_NAME")
    args = parser.parse_args()
    database = os.environ["DB_NAME"]
    if args.apply and args.confirm_db != database:
        parser.error("--apply requires --confirm-db matching DB_NAME")
    candidate = getpass.getpass("Historical shared password to check (not logged): ")
    if not candidate:
        parser.error("A candidate password is required")
    with MongoClient(os.environ["MONGO_URL"]) as client:
        for finding in inspect_accounts(client[database], candidate, args.apply):
            print(finding)


if __name__ == "__main__":
    main()
