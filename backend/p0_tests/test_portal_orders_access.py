"""P0 coverage for the effective, read-only Pedidos access state in the portal."""


def test_portal_team_reflects_module_deactivation_without_mutating_members(services):
    owner = services.restaurant()
    mirror = services.odb.users.find_one({
        "restaurant_id": owner["tid"], "hub_user_id": owner["uid"],
    })
    assert mirror is not None
    before = services.call("GET", "/portal/team", headers=owner["headers"])
    assert before.status_code == 200, before.text
    assert before.headers["Cache-Control"] == "no-store"
    owner_row = next(member for member in before.json()["team"] if member["name"] == mirror["name"])
    assert owner_row["access"] == "granted"

    services.call(
        "POST", f"/hub/tenants/{owner['tid']}/modules/orders/deactivate"
    ).raise_for_status()
    after = services.call("GET", "/portal/team", headers=owner["headers"])
    assert after.status_code == 200, after.text
    owner_row = next(member for member in after.json()["team"] if member["name"] == mirror["name"])
    assert owner_row["access"] == "blocked"

    # The display operation never changes the Pedidos identity or the grant.
    assert services.odb.users.count_documents({"restaurant_id": owner["tid"]}) == 1
