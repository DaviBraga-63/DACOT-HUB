"""Exercise the actual helpers without importing the application or deployment env."""
import ast
import ipaddress
import os
from pathlib import Path
from types import SimpleNamespace


def helpers():
    source = ast.parse((Path(__file__).parents[1] / "server.py").read_text(encoding="utf-8-sig"))
    functions = [node for node in source.body if isinstance(node, ast.FunctionDef)
                 and node.name in {"_client_ip", "_recovery_client_ip"}]
    namespace = {"ipaddress": ipaddress, "os": os, "Request": object}
    exec(compile(ast.Module(body=functions, type_ignores=[]), "proxy_helpers", "exec"), namespace)
    return namespace


def request(peer, forwarded):
    return SimpleNamespace(client=SimpleNamespace(host=peer), headers={"x-forwarded-for": forwarded})


def test_untrusted_peer_cannot_spoof_login_or_recovery_ip(monkeypatch):
    monkeypatch.delenv("RECOVERY_TRUSTED_PROXY_CIDRS", raising=False)
    for name in ("_client_ip", "_recovery_client_ip"):
        assert helpers()[name](request("192.0.2.1", "127.0.0.1")) == "192.0.2.1"


def test_trusted_chain_stops_at_first_untrusted_hop(monkeypatch):
    monkeypatch.setenv("RECOVERY_TRUSTED_PROXY_CIDRS", "10.42.0.0/24")
    for name in ("_client_ip", "_recovery_client_ip"):
        assert helpers()[name](request("10.42.0.2", "127.0.0.1, 192.0.2.5, 10.42.0.3")) == "192.0.2.5"
        assert helpers()[name](request("10.42.0.2", "malformed")) == "unknown"


def test_invalid_trust_configuration_fails_closed(monkeypatch):
    monkeypatch.setenv("RECOVERY_TRUSTED_PROXY_CIDRS", "invalid")
    assert helpers()["_client_ip"](request("10.42.0.2", "192.0.2.1")) == "unknown"
