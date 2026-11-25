import pytest

from whatsapp_delivery import _service_origin, whatsapp_invitation_origin


def test_loopback_transport_is_explicit_and_development_only(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    assert _service_origin("http://127.0.0.1:3004", "local-loopback-http")
    assert not _service_origin("http://example.com:3004", "local-loopback-http")
    assert not _service_origin("http://127.0.0.1:3004", "https")
    assert not _service_origin("http://user@127.0.0.1:3004", "local-loopback-http")
    monkeypatch.setenv("APP_ENV", "production")
    assert not _service_origin("http://127.0.0.1:3004", "local-loopback-http")


def test_invite_origin_can_be_set_independently_only_for_development(monkeypatch):
    frontend = "https://hub.example.test"
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setenv("WHATSAPP_LOCAL_INVITE_ORIGIN", "https://localhost:8443/")
    assert whatsapp_invitation_origin(frontend) == frontend
    monkeypatch.setenv("APP_ENV", "development")
    assert whatsapp_invitation_origin(frontend) == "https://localhost:8443"
    monkeypatch.delenv("WHATSAPP_LOCAL_INVITE_ORIGIN")
    assert whatsapp_invitation_origin(frontend) == frontend


@pytest.mark.parametrize("origin", [
    "http://localhost:8443",
    "https://localhost",
    "https://localhost:65536",
    "https://localhost:8443/login",
    "https://localhost:8443?x=y",
    "https://external.example:8443",
    "https://localhost:8443@external.example",
])
def test_invite_origin_rejects_non_local_or_malformed_values(monkeypatch, origin):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("WHATSAPP_LOCAL_INVITE_ORIGIN", origin)
    with pytest.raises(RuntimeError, match="WHATSAPP_LOCAL_INVITE_ORIGIN"):
        whatsapp_invitation_origin("http://localhost:3000")
