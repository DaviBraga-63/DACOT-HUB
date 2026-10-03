"""Cross-service P0 coverage for aggregate-only Portal revenue."""

import secrets
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import jwt
import requests


def _periods():
    local_now = datetime.now(ZoneInfo("America/Sao_Paulo"))
    today = local_now.replace(hour=12, minute=0, second=0, microsecond=0).astimezone(timezone.utc).isoformat()
    month_extra = local_now.replace(day=1, hour=1, minute=0, second=0, microsecond=0).astimezone(timezone.utc).isoformat()
    prior_month = (local_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0) - timedelta(seconds=1)).astimezone(timezone.utc).isoformat()
    return today, month_extra, prior_month, local_now.day == 1


def _order(restaurant_id, order_number, cents, delivered_at, status="delivered"):
    return {
        "id": secrets.token_hex(12), "restaurant_id": restaurant_id, "order_number": order_number,
        "total_cents": cents, "status": status, "delivered_at": delivered_at,
        "created_at": delivered_at, "updated_at": delivered_at,
    }


def test_portal_revenue_is_aggregate_only_and_tenant_scoped(services):
    service, first, second = services, services.restaurant(), services.restaurant()
    today, month_extra, prior_month, first_day_of_month = _periods()
    service.odb.orders.insert_many([
        _order(first["tid"], 1001, 10_000, today),
        _order(first["tid"], 1002, 2_500, month_extra),
        _order(first["tid"], 1003, 9_999, today, "cancelled"),
        _order(first["tid"], 1004, 8_888, prior_month),
        _order(second["tid"], 1001, 50_000, today),
    ])
    response = service.call(
        "GET", "/portal/analytics/revenue", headers=first["headers"],
        params={"restaurant_id": second["tid"], "tenant_id": second["tid"], "slug": "other"},
    )
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json() == {
        "today_cents": 12_500 if first_day_of_month else 10_000, "current_month_cents": 12_500,
        "currency": "BRL", "timezone": "America/Sao_Paulo",
    }
    assert "orders" not in response.json() and "customers" not in response.json()
    assert service.call("GET", "/portal/analytics/revenue", headers=service.staff).status_code == 403
    assert service.call("GET", "/portal/analytics/revenue", headers={}).status_code == 401


def test_orders_analytics_assertion_is_strict_and_never_selects_another_restaurant(services):
    service, first, second = services, services.restaurant(), services.restaurant()
    _, month_extra, _, _ = _periods()
    service.odb.orders.insert_many([
        _order(first["tid"], 1001, 100, month_extra),
        _order(second["tid"], 1001, 500, month_extra),
    ])
    now = int(datetime.now(timezone.utc).timestamp())

    def assertion(**overrides):
        payload = {
            "iss": "dacot-hub", "aud": "dacot-orders-analytics", "restaurant_id": first["tid"],
            "module": "orders", "scope": "analytics.revenue", "jti": secrets.token_urlsafe(12),
            "iat": now, "nbf": now - 1, "exp": now + 30,
            **overrides,
        }
        return jwt.encode(payload, service.secret, algorithm="HS256")

    endpoint = service.orders + "/api/internal/analytics/revenue"
    valid = requests.get(endpoint, headers={"Authorization": f"Bearer {assertion()}"}, timeout=10)
    assert valid.status_code == 200 and valid.json()["current_month_cents"] == 100
    for token in (
        jwt.encode({"iss": "dacot-hub", "aud": "dacot-orders-analytics", "restaurant_id": first["tid"], "module": "orders", "scope": "analytics.revenue", "jti": "bad", "iat": now, "nbf": now - 1, "exp": now + 30}, "x" * 32, algorithm="HS256"),
        assertion(iss="other"), assertion(aud="dacot-orders"), assertion(exp=now - 1), assertion(restaurant_id=""),
    ):
        assert requests.get(endpoint, headers={"Authorization": f"Bearer {token}"}, timeout=10).status_code == 401


def test_portal_revenue_failure_does_not_become_zero(services):
    service, restaurant = services, services.restaurant()
    original = service.env["ORDERS_BACKEND_URL"]
    try:
        service.env["ORDERS_BACKEND_URL"] = "http://127.0.0.1:1"
        service.restart_hub()
        result = service.call("GET", "/portal/analytics/revenue", headers=restaurant["headers"])
        assert result.status_code == 503
    finally:
        service.env["ORDERS_BACKEND_URL"] = original
        service.restart_hub()
