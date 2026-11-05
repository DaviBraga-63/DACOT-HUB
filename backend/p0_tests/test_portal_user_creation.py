"""Regression coverage: platform administration remains separate from the portal."""

import requests
from uuid import uuid4


def test_platform_staff_can_manage_restaurant_administrators_without_portal_writes(services):
    owner = services.restaurant()
    created = services.call(
        "POST", f"/hub/tenants/{owner['tid']}/users",
        json={
            "name": "Administrador do restaurante", "email": "restaurant-admin@example.com",
            "role": "admin", "password": services.password,
        },
    )
    assert created.status_code == 200, created.text
    assert created.json()["role"] == "admin"

    # A tenant administrator without the explicit owner binding cannot log in
    # to the HUB portal, even though platform staff may manage that account.
    denied = requests.post(
        services.hub + "/api/auth/login",
        json={"email": "restaurant-admin@example.com", "password": services.password},
        headers={"X-DACOT-Tab-Session": str(uuid4())}, timeout=10,
    )
    assert denied.status_code == 401
    assert services.call("POST", "/portal/users", headers=owner["headers"], json={
        "name": "Não permitido", "email": "blocked@example.com", "role": "waiter",
    }).status_code == 404
