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
