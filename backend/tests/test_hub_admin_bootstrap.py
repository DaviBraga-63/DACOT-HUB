"""Iteration 6 — removal of hardcoded hub_users seed credentials.

Covers the audit finding: two extra staff accounts were seeded on every
startup with a hardcoded, plaintext password baked directly into
server.py. This suite pins the fix structurally — it never stores or
reconstructs the old email/password values itself, it only asserts that
the current OPTIONAL_STAFF_SEEDS block cannot contain a literal
credential (every field is either a role/display name or the *name* of
an environment variable) and that the seed loop actually reads from
os.environ. The ADMIN_EMAIL/ADMIN_PASSWORD bootstrap is verified
end-to-end, and no password value is ever logged or returned by the API.

Static-source checks below don't need a running backend — they just
read server.py. The rest need the live API (same as every other suite
here) and are skipped for local ad-hoc runs the same way.

NOTE: this fix only stops the OLD hardcoded accounts from ever being
(re)created or re-asserted going forward. It does NOT retroactively
remove them from a database that already ran the previous version of
this seed — those documents (with the old password hash) remain valid
until someone manually rotates or deletes them. There is deliberately
no runtime test here asserting those old accounts can't log in, because
that assertion is database-state-dependent and would give a false
failure on any already-seeded environment.
"""
import ast
import re
from pathlib import Path

SERVER_PY = Path(__file__).resolve().parents[1] / "server.py"

ENV_VAR_NAME = re.compile(r"[A-Z][A-Z0-9_]*")


def _server_source() -> str:
    return SERVER_PY.read_text(encoding="utf-8")


def _optional_staff_seeds():
    """Parse the OPTIONAL_STAFF_SEEDS list literal out of server.py via
    ast.literal_eval — never by regex-matching or storing any expected
    value — so this test has no opinion on what the old credentials were."""
    src = _server_source()
    start = src.index("OPTIONAL_STAFF_SEEDS = [")
    end = src.index("]", start) + 1
    list_src = src[start:end].split("=", 1)[1].strip()
    return ast.literal_eval(list_src)


class TestSeedHasNoLiteralCredentials:
    def test_optional_seed_block_exists(self):
        src = _server_source()
        assert "OPTIONAL_STAFF_SEEDS" in src, "optional env-driven staff seed block not found"

    def test_seed_entries_carry_no_literal_email_or_password(self):
        """Every entry in OPTIONAL_STAFF_SEEDS must only carry a role, a
        display name, and the *names* of environment variables to read at
        startup — never an actual email or password value."""
        seeds = _optional_staff_seeds()
        assert seeds, "OPTIONAL_STAFF_SEEDS must not be empty"
        for entry in seeds:
            assert set(entry.keys()) == {"role", "email_var", "password_var", "name_var", "default_name"}, entry
            assert "password" not in entry and "email" not in entry, \
                f"seed entry carries a literal credential field: {entry}"
            for key, value in entry.items():
                assert isinstance(value, str) and value, f"{key} must be a non-empty string"
                if key.endswith("_var"):
                    assert ENV_VAR_NAME.fullmatch(value), \
                        f"{key} does not look like an environment variable name: {value!r}"
                else:
                    # role / default_name: must not look like an email or contain '@'
                    assert "@" not in value, f"{key} looks like an email/credential: {value!r}"

    def test_seed_reads_email_and_password_from_environment(self):
        """The seed loop must resolve email/password via os.environ.get using
        the *_var names from OPTIONAL_STAFF_SEEDS — never a literal."""
        src = _server_source()
        assert 'os.environ.get(seed["email_var"]' in src
        assert 'os.environ.get(seed["password_var"]' in src

    def test_seed_code_never_logs_password_value(self):
        """None of the logger calls in the startup/seed section may pass a
        password variable as an argument — only email/role identify the seed
        in logs."""
        src = _server_source()
        start = src.index("async def startup():")
        end = src.index("app.include_router(api_router)")
        startup_src = src[start:end]
        for line in startup_src.splitlines():
            if "logger." not in line:
                continue
            assert "pw" not in line.lower() and "password" not in line.lower(), \
                f"password-looking variable referenced in a log call: {line.strip()}"


class TestBootstrapAdminStillWorks:
    def test_bootstrap_admin_login_works(self, api, test_credentials):
        import requests
        s = requests.Session()
        r = s.post(f"{api}/auth/login", json={"email": test_credentials["email"],
                                              "password": test_credentials["password"]},
                   timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["role"] == "super_admin"
        assert data["user_type"] == "staff"
        assert "password_hash" not in data and "password" not in data

    def test_bootstrap_admin_me_no_password_leak(self, api, client):
        r = client.get(f"{api}/auth/me", timeout=30)
        assert r.status_code == 200
        body = r.json()
        assert "password_hash" not in body and "password" not in body
        # raw body text never contains the word "password" at all
        assert "password" not in r.text.lower()

    def test_login_response_never_leaks_password_fields(self, api, test_credentials):
        import requests
        r = requests.post(f"{api}/auth/login",
                          json={"email": test_credentials["email"],
                                "password": test_credentials["password"]},
                          timeout=30)
        assert r.status_code == 200
        assert "password" not in r.text.lower()

    def test_wrong_password_still_rejected(self, api, test_credentials):
        import requests
        r = requests.post(f"{api}/auth/login",
                          json={"email": test_credentials["email"], "password": "not-the-real-one"},
                          timeout=30)
        assert r.status_code in (401, 429)
