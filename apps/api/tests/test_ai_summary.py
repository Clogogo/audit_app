"""Tests for GET /transactions/ai-summary: content-keyed caching, the
AI-failure fallback that must never surface as a 500, and the term payroll
forecast folded into the prompt when term_id is given.
"""
from datetime import date, timedelta
from unittest.mock import MagicMock

import routers.transactions as transactions_module
from models import Staff, Term


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


def _create_income(client, amount, category, day):
    payload = {
        "type": "income",
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


def test_ai_summary_without_term_id_has_no_forecast_block(client, db_session, monkeypatch):
    # Regression guard: omitting term_id must behave exactly as before.
    transactions_module._AI_SUMMARY_CACHE.clear()
    _create_expense(client, 1000.0, "Fuel Expenses")

    mock_client = MagicMock()
    mock_client.create_message.return_value = "narrative"
    monkeypatch.setattr(transactions_module, "get_llm_client", lambda: mock_client)

    resp = client.get("/transactions/ai-summary")
    assert resp.status_code == 200

    prompt = mock_client.create_message.call_args.kwargs["messages"][0]["content"]
    assert "Remaining staff payroll obligation" not in prompt


def test_ai_summary_term_forecast_covers_payroll_with_no_surplus(client, db_session, monkeypatch):
    # A term ending today: exactly one remaining (unpaid) month — the
    # current one — regardless of what "today" actually is when this test
    # runs, so the whole forecast is deterministic:
    #   remaining_days = 0 -> both projections are exactly 0
    #   remaining_payroll = 1 staff x 1 remaining month = monthly_gross
    #   current_net_position = income_so_far - expenses_so_far
    #
    # term_id is passed WITHOUT start_date/end_date — the term's own dates
    # must be authoritative (regression guard: an out-of-range transaction,
    # 60 days before the term starts, must not leak into the totals).
    transactions_module._AI_SUMMARY_CACHE.clear()
    today = date.today()
    start = today - timedelta(days=5)

    term = Term(name="Test Term", start_date=start, end_date=today)
    db_session.add(term)
    db_session.commit()

    staff = Staff(full_name="Test Teacher", monthly_gross=100000.0, is_active=True)
    db_session.add(staff)
    db_session.commit()

    _create_income(client, 200000.0, "School Fees", start.isoformat())
    _create_expense(client, 100000.0, "Salary and Wages", start.isoformat())
    _create_income(client, 500.0, "Other Income", (start - timedelta(days=60)).isoformat())

    mock_client = MagicMock()
    mock_client.create_message.return_value = "narrative"
    monkeypatch.setattr(transactions_module, "get_llm_client", lambda: mock_client)

    resp = client.get("/transactions/ai-summary", params={"term_id": term.id})
    assert resp.status_code == 200
    assert resp.json()["available"] is True

    prompt = mock_client.create_message.call_args.kwargs["messages"][0]["content"]
    assert "1 month(s) not yet paid, 1 active staff): ₦100,000.00" in prompt
    assert "Current net position this term so far (income minus expenses): ₦100,000.00" in prompt
    assert "Projected surplus/deficit at the end of the term after paying all remaining staff salaries: ₦0.00" in prompt


def test_ai_summary_term_forecast_handles_future_term_without_dividing_by_zero(client, db_session, monkeypatch):
    # A term that hasn't started yet: elapsed_days clamps to 0, so both
    # run-rate projections must be exactly 0 rather than raising ZeroDivisionError.
    transactions_module._AI_SUMMARY_CACHE.clear()
    today = date.today()
    start = today + timedelta(days=10)
    end = today + timedelta(days=40)

    term = Term(name="Future Term", start_date=start, end_date=end)
    db_session.add(term)
    db_session.commit()

    mock_client = MagicMock()
    mock_client.create_message.return_value = "narrative"
    monkeypatch.setattr(transactions_module, "get_llm_client", lambda: mock_client)

    resp = client.get("/transactions/ai-summary", params={"term_id": term.id})
    assert resp.status_code == 200
    assert resp.json()["available"] is True

    prompt = mock_client.create_message.call_args.kwargs["messages"][0]["content"]
    assert "Projected income for the remaining 31 days (based on this term's pace so far): ₦0.00" in prompt


def test_ai_summary_unknown_term_id_returns_404(client, monkeypatch):
    transactions_module._AI_SUMMARY_CACHE.clear()
    mock_client = MagicMock()
    monkeypatch.setattr(transactions_module, "get_llm_client", lambda: mock_client)

    resp = client.get("/transactions/ai-summary", params={"term_id": 999999})
    assert resp.status_code == 404
