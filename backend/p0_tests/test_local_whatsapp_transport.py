from whatsapp_delivery import _service_origin


def test_loopback_transport_is_explicit_and_development_only(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    assert _service_origin("http://127.0.0.1:3004", "local-loopback-http")
    assert not _service_origin("http://example.com:3004", "local-loopback-http")
    assert not _service_origin("http://127.0.0.1:3004", "https")
    assert not _service_origin("http://user@127.0.0.1:3004", "local-loopback-http")
    monkeypatch.setenv("APP_ENV", "production")
    assert not _service_origin("http://127.0.0.1:3004", "local-loopback-http")
