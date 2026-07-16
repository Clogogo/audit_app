"""CRUD tests for /inventory/items, plus the low_stock_only filter and the
computed is_low_stock flag."""


def _create_item(client, **overrides):
    payload = {
        "name": "Grade 5 Maths Textbook",
        "sku": "TXB-005",
        "category": "Textbook",
        "unit": "piece",
        "unit_cost": 1500.0,
        "unit_price": 2500.0,
        "reorder_level": 5,
        "notes": None,
        **overrides,
    }
    resp = client.post("/inventory/items", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_creating_multiple_items_with_a_blank_sku_does_not_collide(client):
    # Regression: a blank SKU is sent as "" (not null) by the frontend's
    # default form state. sku has a UNIQUE constraint, and unlike NULL, two
    # equal empty strings DO collide under that constraint — this crashed
    # with an unhandled IntegrityError (500) on the second such item before
    # the backend started normalizing "" to None.
    first = _create_item(client, name="First Item", sku="")
    second = _create_item(client, name="Second Item", sku="")
    assert first["sku"] is None
    assert second["sku"] is None


def test_updating_an_item_to_a_blank_sku_does_not_collide_with_another_blank_sku_item(client):
    _create_item(client, name="First Item", sku="")
    second = _create_item(client, name="Second Item", sku="ABC-1")

    resp = client.put(f"/inventory/items/{second['id']}", json={
        "name": second["name"], "sku": "", "category": second["category"],
        "unit": second["unit"], "unit_cost": second["unit_cost"], "unit_price": second["unit_price"],
        "reorder_level": second["reorder_level"],
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["sku"] is None


def test_creating_an_item_with_a_genuinely_duplicate_sku_returns_400_not_500(client):
    _create_item(client, name="First Item", sku="DUP-1")
    resp = client.post("/inventory/items", json={
        "name": "Second Item", "sku": "DUP-1", "category": "Book",
        "unit": "piece", "unit_cost": 100.0, "unit_price": 200.0, "reorder_level": 0,
    })
    assert resp.status_code == 400
    assert "DUP-1" in resp.json()["detail"]


def test_categories_endpoint_returns_the_suggested_list(client):
    resp = client.get("/inventory/items/categories")
    assert resp.status_code == 200
    body = resp.json()
    assert "Textbook" in body
    assert "Uniform" in body


def test_category_is_not_restricted_to_the_suggested_list(client):
    # Advisory only, same as Transaction.category — matches assets.py's
    # ASSET_CATEGORIES, which is also never enforced server-side.
    item = _create_item(client, category="Sports Equipment")
    assert item["category"] == "Sports Equipment"


def test_create_and_list_item(client):
    item = _create_item(client)
    assert item["name"] == "Grade 5 Maths Textbook"
    assert item["quantity_on_hand"] == 0
    assert item["is_low_stock"] is True  # 0 <= reorder_level (5)
    assert item["is_active"] is True

    resp = client.get("/inventory/items")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_update_item(client):
    item = _create_item(client)
    resp = client.put(f"/inventory/items/{item['id']}", json={
        "name": "Grade 5 Maths Textbook (Revised)",
        "sku": "TXB-005",
        "category": "Textbook",
        "unit": "piece",
        "unit_cost": 1600.0,
        "unit_price": 2600.0,
        "reorder_level": 5,
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "Grade 5 Maths Textbook (Revised)"
    assert resp.json()["unit_cost"] == 1600.0


def test_update_unknown_item_404s(client):
    resp = client.put("/inventory/items/999999", json={
        "name": "Ghost", "category": "Other",
    })
    assert resp.status_code == 404


def test_delete_item(client):
    item = _create_item(client)
    resp = client.delete(f"/inventory/items/{item['id']}")
    assert resp.status_code == 204

    resp = client.get("/inventory/items")
    assert resp.json() == []


def test_active_only_filter_excludes_inactive_items(client):
    _create_item(client, name="Active Item", sku="A-1", is_active=True)
    _create_item(client, name="Inactive Item", sku="A-2", is_active=False)

    resp = client.get("/inventory/items", params={"active_only": True})
    names = {i["name"] for i in resp.json()}
    assert names == {"Active Item"}


def test_low_stock_only_filter(client):
    # Both start at quantity_on_hand=0 — "low" stays at/below its reorder
    # level; "well stocked" is topped up above its own reorder level via a
    # manual adjustment, the only way quantity_on_hand moves off zero.
    low = _create_item(client, name="Low Stock Item", sku="L-1", reorder_level=10)
    well_stocked = _create_item(client, name="Well Stocked Item", sku="L-2", reorder_level=2)
    adj = client.post("/inventory/movements/adjust", json={
        "item_id": well_stocked["id"], "movement_type": "adjustment_in",
        "quantity": 20, "date": "2026-01-01",
    })
    assert adj.status_code == 201, adj.text

    resp = client.get("/inventory/items", params={"low_stock_only": True})
    body = resp.json()
    assert len(body) == 1
    assert body[0]["id"] == low["id"]
