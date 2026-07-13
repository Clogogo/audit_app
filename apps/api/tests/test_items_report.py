"""Tests for GET /inventory/reports/items: per-item purchase/sale totals
and profit/loss — "what was bought and what was sold", broken out by
item instead of the single grand total in test_sales_summary.py."""


def _create_item(client, name="Grade 5 Maths Textbook", sku="TXB-005", unit_cost=1500.0, unit_price=2500.0, **overrides):
    payload = {
        "name": name, "sku": sku, "category": "Textbook", "unit": "piece",
        "unit_cost": unit_cost, "unit_price": unit_price, "reorder_level": 5,
        **overrides,
    }
    resp = client.post("/inventory/items", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _buy(client, item_id, quantity, unit_amount, request_date="2026-01-10"):
    resp = client.post("/inventory/requests", json={
        "item_id": item_id, "request_type": "purchase", "quantity": quantity,
        "unit_amount": unit_amount, "request_date": request_date,
    })
    assert resp.status_code == 201, resp.text
    fulfill = client.post(f"/inventory/requests/{resp.json()['id']}/fulfill")
    assert fulfill.status_code == 200, fulfill.text


def _sell(client, item_id, quantity, unit_amount, request_date="2026-01-10"):
    resp = client.post("/inventory/requests", json={
        "item_id": item_id, "request_type": "sale", "quantity": quantity,
        "unit_amount": unit_amount, "request_date": request_date,
    })
    assert resp.status_code == 201, resp.text
    fulfill = client.post(f"/inventory/requests/{resp.json()['id']}/fulfill")
    assert fulfill.status_code == 200, fulfill.text


def _report_row(client, item_id, **params):
    resp = client.get("/inventory/reports/items", params=params)
    assert resp.status_code == 200, resp.text
    rows = {r["item_id"]: r for r in resp.json()}
    return rows[item_id]


def test_item_with_no_movements_appears_with_all_zero_fields(client):
    item = _create_item(client)
    row = _report_row(client, item["id"])
    assert row["quantity_on_hand"] == 0
    assert row["total_purchased_quantity"] == 0
    assert row["total_purchase_cost"] == 0.0
    assert row["total_sold_quantity"] == 0
    assert row["total_sale_revenue"] == 0.0
    assert row["costed_revenue"] == 0.0
    assert row["total_profit"] == 0.0
    assert row["profit_margin_pct"] == 0.0
    assert row["sales_missing_cost_count"] == 0


def test_item_totals_combine_purchases_and_sales(client):
    item = _create_item(client, unit_cost=1000.0)
    _buy(client, item["id"], quantity=50, unit_amount=1000.0)
    _buy(client, item["id"], quantity=20, unit_amount=1100.0)   # a later, pricier restock
    _sell(client, item["id"], quantity=10, unit_amount=2500.0)
    _sell(client, item["id"], quantity=5, unit_amount=2500.0)

    row = _report_row(client, item["id"])
    assert row["quantity_on_hand"] == 55   # 50 + 20 - 10 - 5
    assert row["total_purchased_quantity"] == 70
    assert row["total_purchase_cost"] == 50 * 1000.0 + 20 * 1100.0
    assert row["total_sold_quantity"] == 15
    assert row["total_sale_revenue"] == 15 * 2500.0
    # Cost basis for sold units is the item's unit_cost (1000.0) at the
    # moment each sale was fulfilled, not the (possibly different) price
    # paid on either restock — 15 units sold x 1000.0 cost basis each.
    assert row["total_profit"] == 15 * 2500.0 - 15 * 1000.0
    assert row["sales_missing_cost_count"] == 0


def test_report_covers_multiple_items_independently(client):
    book = _create_item(client, name="Book", sku="B-1", unit_cost=1000.0)
    uniform = _create_item(client, name="Uniform", sku="U-1", category="Uniform", unit_cost=4000.0, unit_price=6000.0)

    _buy(client, book["id"], quantity=10, unit_amount=1000.0)
    _sell(client, book["id"], quantity=3, unit_amount=2500.0)

    _buy(client, uniform["id"], quantity=5, unit_amount=4000.0)
    _sell(client, uniform["id"], quantity=2, unit_amount=6000.0)

    resp = client.get("/inventory/reports/items")
    rows = {r["item_id"]: r for r in resp.json()}

    assert rows[book["id"]]["total_sold_quantity"] == 3
    assert rows[book["id"]]["total_profit"] == 3 * 2500.0 - 3 * 1000.0
    assert rows[uniform["id"]]["total_sold_quantity"] == 2
    assert rows[uniform["id"]]["total_profit"] == 2 * 6000.0 - 2 * 4000.0
    # Items' figures never leak into each other.
    assert rows[book["id"]]["total_purchased_quantity"] == 10
    assert rows[uniform["id"]]["total_purchased_quantity"] == 5


def test_report_excludes_zero_cost_sales_from_profit_but_counts_revenue(client):
    # Mirrors test_sales_summary.py's equivalent case: an item nobody
    # priced (unit_cost stays at its 0.0 default) must not silently show
    # a 100% margin.
    item = _create_item(client, unit_cost=0.0)
    _buy(client, item["id"], quantity=10, unit_amount=0.0)
    _sell(client, item["id"], quantity=4, unit_amount=2500.0)

    row = _report_row(client, item["id"])
    assert row["total_sold_quantity"] == 4
    assert row["total_sale_revenue"] == 10000.0
    # No sale here has a known cost, so costed_revenue — the correct
    # denominator for a blended margin — is 0, not 10000.
    assert row["costed_revenue"] == 0.0
    assert row["total_profit"] == 0.0
    assert row["sales_missing_cost_count"] == 1


def test_report_respects_date_range_filters(client, db_session):
    # fulfill_request stamps movements with date.today(), not the
    # request's request_date, so date-range filtering is exercised by
    # inserting movements directly — same approach as
    # test_sales_summary.py::test_summary_respects_date_range_filters.
    from datetime import date as date_cls
    from models import StockMovement

    item = _create_item(client, unit_cost=1000.0)
    db_session.add(StockMovement(
        item_id=item["id"], movement_type="sale_out", quantity=1, unit_amount=2500.0,
        unit_cost=1000.0, date=date_cls(2026, 1, 5),
    ))
    db_session.add(StockMovement(
        item_id=item["id"], movement_type="sale_out", quantity=1, unit_amount=2500.0,
        unit_cost=1000.0, date=date_cls(2026, 3, 5),
    ))
    db_session.commit()

    row = _report_row(client, item["id"], start_date="2026-02-01", end_date="2026-03-31")
    assert row["total_sold_quantity"] == 1
    assert row["total_sale_revenue"] == 2500.0

    # Outside the range entirely: the item still appears, just all-zero.
    row = _report_row(client, item["id"], start_date="2026-06-01", end_date="2026-06-30")
    assert row["total_sold_quantity"] == 0
    assert row["total_sale_revenue"] == 0.0


def test_report_ignores_manual_adjustments(client):
    item = _create_item(client, unit_cost=1000.0)
    client.post("/inventory/movements/adjust", json={
        "item_id": item["id"], "movement_type": "adjustment_in", "quantity": 20, "date": "2026-01-01",
    })

    row = _report_row(client, item["id"])
    assert row["quantity_on_hand"] == 20     # the adjustment did move stock...
    assert row["total_purchased_quantity"] == 0   # ...but isn't counted as a purchase
    assert row["total_sold_quantity"] == 0
