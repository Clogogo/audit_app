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
