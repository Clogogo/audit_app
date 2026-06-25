"""Basic smoke tests — app boots and core endpoints respond."""


def test_docs_endpoint_is_up(client):
    resp = client.get("/docs")
    assert resp.status_code == 200


def test_transactions_summary_endpoint_is_up(client):
    resp = client.get("/transactions/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert "total_income" in body
    assert "total_expenses" in body
