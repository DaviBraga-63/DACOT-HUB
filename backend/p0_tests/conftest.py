"""Real Hub + Pedidos + disposable Mongo. Never loads deployment credentials."""
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time

import pytest
import requests
from pymongo import MongoClient


def port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Services:
    def __init__(self, temp, mongod, orders):
        self.temp = Path(temp)
        self.hub_backend = Path(__file__).resolve().parents[1]
        self.orders_backend = orders
        mp, hp, op = port(), port(), port()
        self.hub = f"http://127.0.0.1:{hp}"
        self.orders = f"http://127.0.0.1:{op}"
        self.key = secrets.token_urlsafe(40)
        self.secret = secrets.token_urlsafe(40)
        self.password = secrets.token_urlsafe(20)
        self.admin_email = "admin@example.com"
        env = {k: v for k, v in os.environ.items() if k.upper() in {
            "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE", "SYSTEMDRIVE",
        }}
        env.update({
            "PYTHON_DOTENV_DISABLED": "1", "PYTHONDONTWRITEBYTECODE": "1",
            "MONGO_URL": f"mongodb://127.0.0.1:{mp}/?directConnection=true",
            "DB_NAME": "hub_p0", "JWT_SECRET": secrets.token_urlsafe(40),
            "HANDOFF_JWT_SECRET": self.secret, "HANDOFF_ISSUER": "dacot-hub",
            "HANDOFF_AUDIENCE": "dacot-orders", "HANDOFF_VERSION": "1", "HANDOFF_MODULE_ID": "orders",
            "HUB_BASE_URL": self.hub, "MODULE_API_KEY": self.key,
            "ADMIN_EMAIL": self.admin_email, "ADMIN_PASSWORD": self.password,
            "FRONTEND_URL": "https://hub.example.test", "EMERGENT_EMAIL_KEY": "",
            "HANDOFF_ALLOWED_ORIGINS_JSON": '{"orders":["https://orders.example.test"]}',
            "APP_ENV": "development", "NO_PROXY": "*", "no_proxy": "*",
        })
        self.env = env
        self.procs = {}
        self.logs = []
        self.mongo = None
        data = self.temp / "db"
        data.mkdir()
        self.start("mongo", [str(mongod), "--bind_ip", "127.0.0.1", "--port", str(mp), "--dbpath", str(data), "--quiet"], self.temp, env)
        self.mongo = MongoClient(env["MONGO_URL"], serverSelectionTimeoutMS=200)
        self.wait(lambda: self.mongo.admin.command("ping"), "mongo")
        self.db = self.mongo.hub_p0
        self.odb = self.mongo.orders_p0
        self.hport, self.oport = hp, op
        self.restart_hub()
        orders_env = {**env, "DB_NAME": "orders_p0", "JWT_SECRET": secrets.token_urlsafe(40),
                      "DEFAULT_RESTAURANT_NAME": "Isolated test bootstrap"}
        self.start("orders", [sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(op)], orders, orders_env)
        self.wait(lambda: requests.get(self.orders + "/api/health", timeout=1).raise_for_status(), "orders")
        assert self.db.tenants.count_documents({}) == 0, "Hub must not seed demo tenants"
        assert self.db.tenant_users.count_documents({}) == 0
        self.staff = self.login(self.admin_email, self.password)

    def start(self, name, command, cwd, env):
        log = (self.temp / f"{name}-{len(self.logs)}.log").open("w")
        self.logs.append(log)
        self.procs[name] = subprocess.Popen(command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT,
                                           creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)

    def wait(self, check, name):
        for _ in range(100):
            if self.procs[name].poll() is not None:
                raise RuntimeError(f"{name} exited: " + "\n".join(p.read_text(errors="replace")[-6000:] for p in self.temp.glob(f"{name}-*.log")))
            try:
                check()
                return
            except Exception:
                time.sleep(.15)
        raise RuntimeError(f"{name} startup timeout")

    def stop(self, name):
        process = self.procs.pop(name, None)
        if process:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

    def restart_hub(self):
        self.stop("hub")
        self.start("hub", [sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(self.hport)], self.hub_backend, self.env)
        self.wait(lambda: requests.get(self.hub + "/api/", timeout=1).raise_for_status(), "hub")

    def login(self, email, password):
        r = requests.post(self.hub + "/api/auth/login", json={"email": email, "password": password}, timeout=10)
        r.raise_for_status()
        return {"Authorization": "Bearer " + r.cookies["access_token"]}

    def call(self, method, path, **kwargs):
        kwargs.setdefault("headers", self.staff)
        return requests.request(method, self.hub + "/api" + path, timeout=10, **kwargs)

    def restaurant(self):
        tag = secrets.token_hex(6)
        r = self.call("POST", "/hub/tenants", json={"name": tag, "owner_name": "Test", "email": f"{tag}@example.com", "status": "active"})
        r.raise_for_status()
        tid = r.json()["id"]
        self.call("POST", f"/hub/tenants/{tid}/modules/orders/activate").raise_for_status()
        self.call("PATCH", f"/hub/tenants/{tid}/modules/orders", json={"launch_url": f"https://orders.example.test/{tag}"}).raise_for_status()
        r = self.call("POST", f"/hub/tenants/{tid}/users", json={"name": "Test", "email": f"u{tag}@example.com", "role": "admin", "password": self.password})
        r.raise_for_status()
        uid = r.json()["id"]
        return {"tid": tid, "uid": uid, "headers": self.login(f"u{tag}@example.com", self.password)}

    def handoff(self, identity):
        r = self.call("POST", "/portal/modules/orders/launch-token", headers=identity["headers"])
        r.raise_for_status()
        return r.json()["handoff"]

    def exchange(self, token):
        return requests.post(self.orders + "/api/orders/session/exchange", json={"handoff": token}, timeout=10)

    def order_me(self, token):
        return requests.get(self.orders + "/api/auth/me", headers={"Authorization": "Bearer " + token}, timeout=10)

    def close(self):
        for name in ("orders", "hub", "mongo"):
            self.stop(name)
        if self.mongo:
            self.mongo.close()
        for log in self.logs:
            log.close()


@pytest.fixture(scope="session")
def services():
    mongod = Path(os.environ["P0_MONGOD"]).resolve(strict=True)
    orders = Path(os.environ["P0_ORDERS_BACKEND"]).resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="dacot-hub-p0-") as temp:
        service = Services.__new__(Services)
        service.procs, service.logs, service.mongo = {}, [], None
        try:
            service.__init__(temp, mongod, orders)
            yield service
        finally:
            service.close()
