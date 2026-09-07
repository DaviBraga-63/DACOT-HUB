import os
import re
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values

frontend_env = dotenv_values("/app/frontend/.env")
backend_env = dotenv_values("/app/backend/.env")
base_url = os.environ.get("REACT_APP_BACKEND_URL") or frontend_env.get("REACT_APP_BACKEND_URL")
if not base_url:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
BASE_URL = base_url.rstrip("/")
API = f"{BASE_URL}/api"

CREDS_PATH = Path("/app/memory/test_credentials.md")


def _parse_credentials():
    """Parse the markdown credential tables (staff + restaurant users)."""
    if not CREDS_PATH.exists():
        return {}, {}
    text = CREDS_PATH.read_text(encoding="utf-8")
    staff, restaurant = {}, {}
    tenant_pw = None
    m = re.search(r"Senha de todos os seeds:\s*\*\*([^*]+)\*\*", text)
    if m:
        tenant_pw = m.group(1).strip()
    section = None
    for line in text.splitlines():
        low = line.lower()
        if low.startswith("##"):
            if "staff" in low:
                section = "staff"
            elif "restaurante" in low and "clientes" in low:
                section = "restaurant"
            else:
                section = None
            continue
        if not line.strip().startswith("|") or section is None:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3 or "@" not in cells[0]:
            continue
        if section == "staff":
            staff[cells[2]] = {"email": cells[0], "password": cells[1], "role": cells[2]}
        else:
            restaurant[cells[0]] = {"email": cells[0], "password": tenant_pw,
                                    "tenant_name": cells[1], "role": cells[2]}
    return staff, restaurant


STAFF_CREDS, RESTAURANT_CREDS = _parse_credentials()


@pytest.fixture(scope="session")
def api():
    return API


@pytest.fixture(scope="session")
def env_backend():
    return backend_env


@pytest.fixture(scope="session")
def test_credentials():
    if "super_admin" not in STAFF_CREDS:
        pytest.skip("no super_admin credentials parsed from test_credentials.md")
    return STAFF_CREDS["super_admin"]


def _login(creds):
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": creds["email"], "password": creds["password"]},
               timeout=30)
    if r.status_code != 200:
        pytest.fail(f"login failed for {creds['email']}: {r.status_code} {r.text[:300]}")
    return s, r.json()


@pytest.fixture(scope="session")
def client(test_credentials):
    """super_admin session (backwards-compatible name)."""
    s, _ = _login(test_credentials)
    return s


def _optional_staff_creds(role, email_var, password_var):
    """Credentials for the optional STAFF_ADMIN_*/STAFF_VIEWER_* seed accounts
    (see backend/server.py OPTIONAL_STAFF_SEEDS), read from the backend's own
    .env — the single source of truth for whether those accounts even exist.
    Falls back to a matching row in test_credentials.md (if present) for
    environments that provision that role a different way. No credential is
    ever hardcoded here."""
    email = backend_env.get(email_var)
    password = backend_env.get(password_var)
    if email and password:
        return {"email": email, "password": password, "role": role}
    if role in STAFF_CREDS:
        return STAFF_CREDS[role]
    return None


@pytest.fixture(scope="session")
def staff_admin_creds():
    """Credentials dict only (no login) — for tests that need their own
    independent session, e.g. because they log it out or otherwise mutate
    its state and must not disturb the shared `staff_admin` session."""
    creds = _optional_staff_creds("admin", "STAFF_ADMIN_EMAIL", "STAFF_ADMIN_PASSWORD")
    if not creds:
        pytest.skip("no 'admin' staff credentials available — set STAFF_ADMIN_EMAIL/"
                    "STAFF_ADMIN_PASSWORD in backend/.env or add an 'admin' row to "
                    "test_credentials.md")
    return creds


@pytest.fixture(scope="session")
def staff_admin(staff_admin_creds):
    s, _ = _login(staff_admin_creds)
    return s


@pytest.fixture(scope="session")
def staff_viewer_creds():
    """Credentials dict only (no login) — see staff_admin_creds."""
    creds = _optional_staff_creds("viewer", "STAFF_VIEWER_EMAIL", "STAFF_VIEWER_PASSWORD")
    if not creds:
        pytest.skip("no 'viewer' staff credentials available — set STAFF_VIEWER_EMAIL/"
                    "STAFF_VIEWER_PASSWORD in backend/.env or add a 'viewer' row to "
                    "test_credentials.md")
    return creds


@pytest.fixture(scope="session")
def staff_viewer(staff_viewer_creds):
    s, _ = _login(staff_viewer_creds)
    return s


@pytest.fixture(scope="session")
def client_a_admin():
    s, data = _login(RESTAURANT_CREDS["joao@hamburgueriaexemplo.com"])
    return s, data


@pytest.fixture(scope="session")
def client_a_waiter():
    s, data = _login(RESTAURANT_CREDS["pedro@hamburgueriaexemplo.com"])
    return s, data


@pytest.fixture(scope="session")
def client_b_kitchen():
    s, data = _login(RESTAURANT_CREDS["marco@bellanapoli.com.br"])
    return s, data


@pytest.fixture(scope="session")
def anon():
    return requests.Session()


def _find_tenant(client, q):
    r = client.get(f"{API}/hub/tenants", params={"q": q}, timeout=30)
    assert r.status_code == 200, r.text
    items = r.json()
    items = items if isinstance(items, list) else items.get("items", [])
    assert items, f"tenant '{q}' not found"
    return items[0]


@pytest.fixture(scope="session")
def hamburgueria(client):
    return _find_tenant(client, "hamburgueria")


@pytest.fixture(scope="session")
def bella_napoli(client):
    return _find_tenant(client, "bella")
