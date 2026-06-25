"""Tests for GET /transactions/ai-summary: content-keyed caching and the
AI-failure fallback that must never surface as a 500.
"""
from unittest.mock import MagicMock

import routers.transactions as transactions_module


def _create_expense(client, amount, category, day="2026-02-10"):
    payload = {
        "type": "expense",
        "amount": amount,
        "currency": "NGN",
        "category": category,
        "description": "test",
        "date": day,
    }
    resp = client.post("/transactions", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_ai_summary_returns_narrative_and_caches_identical_data(client, monkeypatch):
    transactions_module._AI_SUMMARY_CACHE.clear()
    _create_expense(client, 1000.0, "Fuel Expenses")

    mock_client = MagicMock()
    mock_client.create_message.return_value = "Spending is concentrated on fuel."
    monkeypatch.setattr(transactions_module, "get_llm_client", lambda: mock_client)

    resp = client.get("/transactions/ai-summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is True
    assert body["narrative"] == "Spending is concentrated on fuel."
    assert mock_client.create_message.call_count == 1

    # Same underlying totals -> cache hit, no second AI call
    resp2 = client.get("/transactions/ai-summary")
    assert resp2.json()["narrative"] == "Spending is concentrated on fuel."
    assert mock_client.create_message.call_count == 1


def test_ai_summary_cache_invalidates_when_totals_change(client, monkeypatch):
    transactions_module._AI_SUMMARY_CACHE.clear()
    _create_expense(client, 500.0, "Fuel Expenses")

    mock_client = MagicMock()
    mock_client.create_message.side_effect = ["First narrative", "Second narrative"]
    monkeypatch.setattr(transactions_module, "get_llm_client", lambda: mock_client)

    first = client.get("/transactions/ai-summary").json()
    assert first["narrative"] == "First narrative"

    _create_expense(client, 250.0, "Fuel Expenses")

    second = client.get("/transactions/ai-summary").json()
    assert second["narrative"] == "Second narrative"
    assert mock_client.create_message.call_count == 2


def test_ai_summary_unavailable_on_ai_failure(client, monkeypatch):
    transactions_module._AI_SUMMARY_CACHE.clear()
    _create_expense(client, 100.0, "Fuel Expenses")

    def _raise():
        raise ValueError("OPENROUTER_API_KEY environment variable not set.")

    monkeypatch.setattr(transactions_module, "get_llm_client", _raise)

    resp = client.get("/transactions/ai-summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is False
    assert body["narrative"] is None
