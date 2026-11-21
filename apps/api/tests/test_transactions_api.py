"""CRUD round-trip tests for /transactions, including a regression test for
the reported bug where editing a transaction's category zeroed its amount.
"""


def _create(client, **overrides):
    payload = {
        "type": "expense",
        "amount": 5000.0,
        "currency": "NGN",
        "category": "Fuel Expenses",
        "description": "Test transaction",
        "date": "2026-01-15",
        **overrides,
    }
    resp = client.post("/transactions", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_create_expense_and_income_transactions(client):
    expense = _create(client, type="expense", amount=1200.0, category="Bank Charges")
    income = _create(client, type="income", amount=50000.0, category="School Fees")

    assert expense["amount"] == 1200.0
    assert expense["type"] == "expense"
    assert income["amount"] == 50000.0
    assert income["type"] == "income"


def test_list_and_filter_by_type(client):
    _create(client, type="expense", amount=100.0)
    _create(client, type="income", amount=200.0)

    resp = client.get("/transactions", params={"type": "income"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["type"] == "income"


def test_updating_only_category_does_not_change_amount(client):
    """Regression test: PUT with just {category: ...} must leave amount alone."""
    tx = _create(client, amount=7500.5, category="Fuel Expenses")

    resp = client.put(f"/transactions/{tx['id']}", json={"category": "Repairs and Maintenance"})
    assert resp.status_code == 200, resp.text
    updated = resp.json()

    assert updated["category"] == "Repairs and Maintenance"
    assert updated["amount"] == 7500.5


def test_update_can_still_change_amount_explicitly(client):
    tx = _create(client, amount=100.0)

    resp = client.put(f"/transactions/{tx['id']}", json={"amount": 250.0})
    assert resp.status_code == 200
    assert resp.json()["amount"] == 250.0


def test_delete_transaction(client):
    tx = _create(client)

    resp = client.delete(f"/transactions/{tx['id']}")
    assert resp.status_code == 200

    resp = client.get("/transactions", params={"type": tx["type"]})
    assert all(item["id"] != tx["id"] for item in resp.json()["items"])


def test_ai_recategorize_suggests_only_valid_changes_and_saves_nothing(client, db_session, monkeypatch):
    import json
    import ai_worker
    from datetime import date
    from models import Transaction
    rows = [Transaction(type="expense", amount=10, currency="NGN", category="Other", description="MTN airtime", date=date(2026, 8, 1), vendor="V"),
            Transaction(type="expense", amount=20, currency="NGN", category="Other", description="x", date=date(2026, 8, 1), vendor="V"),
            Transaction(type="transfer", amount=30, currency="NGN", category="Other", description="y", date=date(2026, 8, 1), vendor="V")]
    db_session.add_all(rows)
    db_session.commit()
    a, b, t = (r.id for r in rows)
    monkeypatch.setattr(ai_worker, "call_ai_text", lambda *_: json.dumps(
        [{"id": a, "category": "Telephone"}, {"id": b, "category": "Not A Category"}, {"id": t, "category": "Telephone"}]))
    out = client.post("/transactions/ai-recategorize", json={"ids": [a, b, t]})
    assert out.status_code == 200
    assert out.json() == {"checked": 2, "suggestions": [{"id": a, "from": "Other", "to": "Telephone"}]}
    db_session.expire_all()
    assert db_session.get(Transaction, a).category == "Other"


def test_ai_recategorize_reports_an_unavailable_ai(client, db_session, monkeypatch):
    import ai_worker
    from datetime import date
    from models import Transaction
    tx = Transaction(type="expense", amount=10, currency="NGN", category="Other", description="d", date=date(2026, 8, 1), vendor="V")
    db_session.add(tx)
    db_session.commit()
    monkeypatch.setattr(ai_worker, "call_ai_text", lambda *_: "")
    assert client.post("/transactions/ai-recategorize", json={"ids": [tx.id]}).status_code == 503
