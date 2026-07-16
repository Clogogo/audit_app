"""Tests for /inventory/movements: the read-only ledger and the manual
/movements/adjust endpoint that bypasses the request workflow entirely."""


def _create_item(client, **overrides):
    payload = {
        "name": "Storybook Set", "sku": "BK-001", "category": "Book",
        "unit": "set", "unit_cost": 800.0, "unit_price": 1200.0, "reorder_level": 2,
        **overrides,
    }
    resp = client.post("/inventory/items", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_adjustment_in_increases_quantity_and_logs_a_movement(client):
    item = _create_item(client)
    resp = client.post("/inventory/movements/adjust", json={
        "item_id": item["id"], "movement_type": "adjustment_in",
        "quantity": 15, "date": "2026-02-01", "notes": "Found extra stock during physical count",
    })
    assert resp.status_code == 201, resp.text
    assert resp.json()["movement_type"] == "adjustment_in"
    assert resp.json()["quantity"] == 15

    updated_item = client.get("/inventory/items").json()[0]
    assert updated_item["quantity_on_hand"] == 15


def test_adjustment_out_decreases_quantity(client):
    item = _create_item(client)
    client.post("/inventory/movements/adjust", json={
        "item_id": item["id"], "movement_type": "adjustment_in", "quantity": 10, "date": "2026-02-01",
    })
    resp = client.post("/inventory/movements/adjust", json={
        "item_id": item["id"], "movement_type": "adjustment_out",
        "quantity": 3, "date": "2026-02-02", "notes": "Damaged in storage",
    })
    assert resp.status_code == 201

    updated_item = client.get("/inventory/items").json()[0]
    assert updated_item["quantity_on_hand"] == 7


def test_adjustment_out_rejected_when_it_would_go_negative(client):
    item = _create_item(client)
    resp = client.post("/inventory/movements/adjust", json={
        "item_id": item["id"], "movement_type": "adjustment_out",
        "quantity": 5, "date": "2026-02-01",
    })
    assert resp.status_code == 400

    updated_item = client.get("/inventory/items").json()[0]
    assert updated_item["quantity_on_hand"] == 0


def test_adjustment_rejects_unknown_movement_type(client):
    item = _create_item(client)
    resp = client.post("/inventory/movements/adjust", json={
        "item_id": item["id"], "movement_type": "purchase_in",
        "quantity": 5, "date": "2026-02-01",
    })
    assert resp.status_code == 400


def test_adjustment_rejects_nonpositive_quantity(client):
    item = _create_item(client)
    resp = client.post("/inventory/movements/adjust", json={
        "item_id": item["id"], "movement_type": "adjustment_in",
        "quantity": 0, "date": "2026-02-01",
    })
    assert resp.status_code == 400


def test_adjustment_for_unknown_item_404s(client):
    resp = client.post("/inventory/movements/adjust", json={
        "item_id": 999999, "movement_type": "adjustment_in",
        "quantity": 5, "date": "2026-02-01",
    })
    assert resp.status_code == 404


def test_movements_list_filters_by_item_and_date_range(client):
    item_a = _create_item(client, name="Item A", sku="A-1")
    item_b = _create_item(client, name="Item B", sku="A-2")
    client.post("/inventory/movements/adjust", json={
        "item_id": item_a["id"], "movement_type": "adjustment_in", "quantity": 5, "date": "2026-01-05",
    })
    client.post("/inventory/movements/adjust", json={
        "item_id": item_b["id"], "movement_type": "adjustment_in", "quantity": 5, "date": "2026-03-05",
    })

    resp = client.get("/inventory/movements", params={"item_id": item_a["id"]})
    assert len(resp.json()) == 1
    assert resp.json()[0]["item_name"] == "Item A"

    resp = client.get("/inventory/movements", params={"start_date": "2026-02-01", "end_date": "2026-03-31"})
    assert len(resp.json()) == 1
    assert resp.json()[0]["item_name"] == "Item B"
