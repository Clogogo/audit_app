"""Tests for /inventory/requests: the pending -> fulfilled/cancelled
workflow, quantity_on_hand updates on fulfillment, and the guard against a
sale fulfillment that would take stock negative."""


def _create_item(client, quantity_on_hand=0, **overrides):
    payload = {
        "name": "School Uniform (Size M)", "sku": "UNI-M", "category": "Uniform",
        "unit": "piece", "unit_cost": 4000.0, "unit_price": 6000.0, "reorder_level": 3,
        **overrides,
    }
    resp = client.post("/inventory/items", json=payload)
    assert resp.status_code == 201, resp.text
    item = resp.json()
    if quantity_on_hand:
        adj = client.post("/inventory/movements/adjust", json={
            "item_id": item["id"], "movement_type": "adjustment_in",
            "quantity": quantity_on_hand, "date": "2026-01-01",
        })
        assert adj.status_code == 201, adj.text
        item = client.get("/inventory/items").json()[0]
    return item


def _create_request(client, item_id, request_type="purchase", quantity=10, unit_amount=4000.0, **overrides):
    payload = {
        "item_id": item_id, "request_type": request_type, "quantity": quantity,
        "unit_amount": unit_amount, "counterparty": "ABC Suppliers",
        "request_date": "2026-01-10", **overrides,
    }
    resp = client.post("/inventory/requests", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_create_request_defaults_to_pending(client):
    item = _create_item(client)
    req = _create_request(client, item["id"])
    assert req["status"] == "pending"
    assert req["item_name"] == "School Uniform (Size M)"
    assert req["fulfilled_date"] is None


def test_create_request_rejects_unknown_type(client):
    item = _create_item(client)
    resp = client.post("/inventory/requests", json={
        "item_id": item["id"], "request_type": "return", "quantity": 1,
        "unit_amount": 100.0, "request_date": "2026-01-10",
    })
    assert resp.status_code == 400


def test_create_request_rejects_nonpositive_quantity(client):
    item = _create_item(client)
    resp = client.post("/inventory/requests", json={
        "item_id": item["id"], "request_type": "purchase", "quantity": 0,
        "unit_amount": 100.0, "request_date": "2026-01-10",
    })
    assert resp.status_code == 400


def test_create_request_for_unknown_item_404s(client):
    resp = client.post("/inventory/requests", json={
        "item_id": 999999, "request_type": "purchase", "quantity": 1,
        "unit_amount": 100.0, "request_date": "2026-01-10",
    })
    assert resp.status_code == 404


def test_fulfilling_a_purchase_increases_quantity_on_hand(client):
    item = _create_item(client, quantity_on_hand=5)
    req = _create_request(client, item["id"], request_type="purchase", quantity=20)

    resp = client.post(f"/inventory/requests/{req['id']}/fulfill")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "fulfilled"
    assert body["fulfilled_date"] is not None

    updated_item = client.get("/inventory/items").json()[0]
    assert updated_item["quantity_on_hand"] == 25

    movements = client.get("/inventory/movements").json()
    assert len(movements) == 2  # the setup adjustment_in + this purchase_in
    latest = movements[0]
    assert latest["movement_type"] == "purchase_in"
    assert latest["quantity"] == 20
    assert latest["request_id"] == req["id"]


def test_fulfilling_a_sale_decreases_quantity_on_hand(client):
    item = _create_item(client, quantity_on_hand=10)
    req = _create_request(client, item["id"], request_type="sale", quantity=4, unit_amount=6000.0)

    resp = client.post(f"/inventory/requests/{req['id']}/fulfill")
    assert resp.status_code == 200, resp.text

    updated_item = client.get("/inventory/items").json()[0]
    assert updated_item["quantity_on_hand"] == 6

    movements = client.get("/inventory/movements", params={"movement_type": "sale_out"}).json()
    assert len(movements) == 1
    assert movements[0]["quantity"] == 4


def test_fulfilling_a_sale_that_would_go_negative_is_rejected(client):
    item = _create_item(client, quantity_on_hand=2)
    req = _create_request(client, item["id"], request_type="sale", quantity=5, unit_amount=6000.0)

    resp = client.post(f"/inventory/requests/{req['id']}/fulfill")
    assert resp.status_code == 400

    # Neither stock nor the request status may change on rejection.
    updated_item = client.get("/inventory/items").json()[0]
    assert updated_item["quantity_on_hand"] == 2
    unchanged_req = client.get("/inventory/requests").json()[0]
    assert unchanged_req["status"] == "pending"


def test_cancel_leaves_quantity_on_hand_untouched(client):
    item = _create_item(client, quantity_on_hand=10)
    req = _create_request(client, item["id"], request_type="purchase", quantity=50)

    resp = client.post(f"/inventory/requests/{req['id']}/cancel")
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"

    updated_item = client.get("/inventory/items").json()[0]
    assert updated_item["quantity_on_hand"] == 10
    movements = client.get("/inventory/movements").json()
    assert all(m["movement_type"] == "adjustment_in" for m in movements)


def test_cannot_fulfill_a_non_pending_request(client):
    item = _create_item(client, quantity_on_hand=10)
    req = _create_request(client, item["id"], request_type="purchase", quantity=5)
    client.post(f"/inventory/requests/{req['id']}/cancel")

    resp = client.post(f"/inventory/requests/{req['id']}/fulfill")
    assert resp.status_code == 400


def test_cannot_cancel_a_non_pending_request(client):
    item = _create_item(client, quantity_on_hand=10)
    req = _create_request(client, item["id"], request_type="purchase", quantity=5)
    client.post(f"/inventory/requests/{req['id']}/fulfill")

    resp = client.post(f"/inventory/requests/{req['id']}/cancel")
    assert resp.status_code == 400


def test_cannot_edit_or_delete_a_non_pending_request(client):
    item = _create_item(client, quantity_on_hand=10)
    req = _create_request(client, item["id"], request_type="purchase", quantity=5)
    client.post(f"/inventory/requests/{req['id']}/fulfill")

    resp = client.put(f"/inventory/requests/{req['id']}", json={
        "item_id": item["id"], "request_type": "purchase", "quantity": 99,
        "unit_amount": 1.0, "request_date": "2026-01-10",
    })
    assert resp.status_code == 400

    resp = client.delete(f"/inventory/requests/{req['id']}")
    assert resp.status_code == 400


def test_list_requests_filters_by_type_and_status(client):
    item = _create_item(client, quantity_on_hand=10)
    purchase = _create_request(client, item["id"], request_type="purchase", quantity=5)
    sale = _create_request(client, item["id"], request_type="sale", quantity=2, unit_amount=6000.0)
    client.post(f"/inventory/requests/{sale['id']}/fulfill")

    resp = client.get("/inventory/requests", params={"request_type": "purchase"})
    assert {r["id"] for r in resp.json()} == {purchase["id"]}

    resp = client.get("/inventory/requests", params={"status": "fulfilled"})
    assert {r["id"] for r in resp.json()} == {sale["id"]}
