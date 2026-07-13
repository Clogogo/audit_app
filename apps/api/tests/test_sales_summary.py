"""Tests for GET /inventory/sales-summary: revenue/cost/profit aggregation
across fulfilled sales, and the guard against treating an unknown cost
(pre-cost-snapshot sales) as zero cost."""


def _create_item(client, unit_cost=1500.0, unit_price=2500.0, quantity_on_hand=0, **overrides):
    payload = {
        "name": "Grade 5 Maths Textbook", "sku": "TXB-005", "category": "Textbook",
        "unit": "piece", "unit_cost": unit_cost, "unit_price": unit_price, "reorder_level": 5,
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
    return item


def _sell(client, item_id, quantity, unit_amount, request_date="2026-01-10"):
    resp = client.post("/inventory/requests", json={
        "item_id": item_id, "request_type": "sale", "quantity": quantity,
        "unit_amount": unit_amount, "request_date": request_date,
    })
    assert resp.status_code == 201, resp.text
    req_id = resp.json()["id"]
    fulfill = client.post(f"/inventory/requests/{req_id}/fulfill")
    assert fulfill.status_code == 200, fulfill.text


def test_empty_summary_when_no_sales(client):
    resp = client.get("/inventory/sales-summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "total_sales_count": 0, "total_revenue": 0.0, "total_cost": 0.0,
        "total_profit": 0.0, "profit_margin_pct": 0.0, "sales_missing_cost_count": 0,
    }


def test_summary_computes_revenue_cost_and_profit_across_multiple_sales(client):
    item = _create_item(client, unit_cost=1000.0, quantity_on_hand=100)
    _sell(client, item["id"], quantity=5, unit_amount=2500.0)   # revenue 12500, cost 5000
    _sell(client, item["id"], quantity=3, unit_amount=2500.0)   # revenue 7500, cost 3000

    resp = client.get("/inventory/sales-summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_sales_count"] == 2
    assert body["total_revenue"] == 20000.0
    assert body["total_cost"] == 8000.0
    assert body["total_profit"] == 12000.0
    assert body["profit_margin_pct"] == 60.0
    assert body["sales_missing_cost_count"] == 0


def test_summary_excludes_unpriced_sales_from_cost_and_profit_but_not_revenue(client, db_session):
    from datetime import date
    from models import StockMovement

    item = _create_item(client, unit_cost=1000.0, quantity_on_hand=100)
    _sell(client, item["id"], quantity=5, unit_amount=2500.0)  # normal, priced sale

    # Simulate a pre-cost-snapshot sale: a sale_out row with unit_cost still
    # NULL, as any row fulfilled before this feature existed would be.
    legacy_sale = StockMovement(
        item_id=item["id"], movement_type="sale_out", quantity=2, unit_amount=2500.0,
        unit_cost=None, date=date(2026, 1, 5),
    )
    db_session.add(legacy_sale)
    db_session.commit()

    resp = client.get("/inventory/sales-summary")
    body = resp.json()
    assert body["total_sales_count"] == 2
    assert body["sales_missing_cost_count"] == 1
    # Revenue includes both sales: priced (5 x 2500 = 12500) + legacy (2 x 2500 = 5000).
    assert body["total_revenue"] == 17500.0
    # Cost/profit only reflect the priced sale (5 x 1000 cost, 5 x 2500 revenue).
    assert body["total_cost"] == 5000.0
    assert body["total_profit"] == 7500.0


def test_summary_respects_date_range_filters(client, db_session):
    # fulfill_request always stamps a movement with date.today() (the date
    # stock actually moved), not the request's intended request_date — so
    # date-range filtering is exercised by inserting movements directly.
    from datetime import date
    from models import StockMovement

    item = _create_item(client, unit_cost=1000.0)
    db_session.add(StockMovement(
        item_id=item["id"], movement_type="sale_out", quantity=1, unit_amount=2500.0,
        unit_cost=1000.0, date=date(2026, 1, 5),
    ))
    db_session.add(StockMovement(
        item_id=item["id"], movement_type="sale_out", quantity=1, unit_amount=2500.0,
        unit_cost=1000.0, date=date(2026, 3, 5),
    ))
    db_session.commit()

    resp = client.get("/inventory/sales-summary", params={"start_date": "2026-02-01", "end_date": "2026-03-31"})
    body = resp.json()
    assert body["total_sales_count"] == 1
    assert body["total_revenue"] == 2500.0


def test_summary_ignores_purchases_and_adjustments(client):
    item = _create_item(client, unit_cost=1000.0)
    # A purchase and a manual adjustment both move stock, but neither is a sale.
    resp = client.post("/inventory/requests", json={
        "item_id": item["id"], "request_type": "purchase", "quantity": 10,
        "unit_amount": 1000.0, "request_date": "2026-01-01",
    })
    client.post(f"/inventory/requests/{resp.json()['id']}/fulfill")
    client.post("/inventory/movements/adjust", json={
        "item_id": item["id"], "movement_type": "adjustment_in", "quantity": 5, "date": "2026-01-02",
    })

    resp = client.get("/inventory/sales-summary")
    body = resp.json()
    assert body["total_sales_count"] == 0
    assert body["total_revenue"] == 0.0


def test_summary_excludes_zero_cost_items_from_cost_and_profit(client):
    # unit_cost defaults to 0.0 (not nullable), so an item nobody ever
    # priced looks identical to a genuine free item at the model level.
    # Fulfillment treats 0.0 as "unknown" (see test_stock_requests.py) —
    # this confirms the summary endpoint honors that: the sale still counts
    # toward revenue, but is excluded from cost/profit like any other
    # missing-cost sale, not counted as a 100%-margin sale.
    item = _create_item(client, unit_cost=0.0, quantity_on_hand=10)
    _sell(client, item["id"], quantity=3, unit_amount=2500.0)

    resp = client.get("/inventory/sales-summary")
    body = resp.json()
    assert body["total_sales_count"] == 1
    assert body["sales_missing_cost_count"] == 1
    assert body["total_revenue"] == 7500.0
    assert body["total_cost"] == 0.0
    assert body["total_profit"] == 0.0
