"""Tests for GET /staff-directory/ai-summary: content-keyed caching, the
AI-failure fallback that must never surface as a 500, and that the prompt
reflects staff loans, advances (IOUs), payroll status, and the current term.
"""
from datetime import date, timedelta
from unittest.mock import MagicMock

import routers.staff_directory as staff_directory_module
from models import AdvancePayment, PayrollEntry, Staff, StaffLoan, StaffLoanPayment, Term


def _create_staff(db_session, full_name="Ngozi Williams", monthly_gross=100000.0, is_active=True) -> Staff:
    staff = Staff(full_name=full_name, monthly_gross=monthly_gross, is_active=is_active)
    db_session.add(staff)
    db_session.commit()
    return staff


def test_staff_ai_summary_returns_narrative_and_caches_identical_data(client, db_session, monkeypatch):
    staff_directory_module._STAFF_AI_SUMMARY_CACHE.clear()
    _create_staff(db_session)

    mock_client = MagicMock()
    mock_client.create_message.return_value = "Staffing is stable this month."
    monkeypatch.setattr(staff_directory_module, "get_llm_client", lambda: mock_client)

    resp = client.get("/staff-directory/ai-summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is True
    assert body["narrative"] == "Staffing is stable this month."
    assert mock_client.create_message.call_count == 1

    # Same underlying figures -> cache hit, no second AI call
    resp2 = client.get("/staff-directory/ai-summary")
    assert resp2.json()["narrative"] == "Staffing is stable this month."
    assert mock_client.create_message.call_count == 1


def test_staff_ai_summary_cache_invalidates_when_staff_changes(client, db_session, monkeypatch):
    staff_directory_module._STAFF_AI_SUMMARY_CACHE.clear()
    _create_staff(db_session, "Ngozi Williams")

    mock_client = MagicMock()
    mock_client.create_message.side_effect = ["First narrative", "Second narrative"]
    monkeypatch.setattr(staff_directory_module, "get_llm_client", lambda: mock_client)

    first = client.get("/staff-directory/ai-summary").json()
    assert first["narrative"] == "First narrative"

    _create_staff(db_session, "Chidi Okafor")

    second = client.get("/staff-directory/ai-summary").json()
    assert second["narrative"] == "Second narrative"
    assert mock_client.create_message.call_count == 2


def test_staff_ai_summary_retries_without_extra_body_on_older_openai_client(client, db_session, monkeypatch):
    staff_directory_module._STAFF_AI_SUMMARY_CACHE.clear()
    _create_staff(db_session)

    mock_client = MagicMock()
    mock_client.create_message.side_effect = [
        TypeError("create_message() got an unexpected keyword argument 'extra_body'"),
        "Fallback narrative without reasoning control.",
    ]
    monkeypatch.setattr(staff_directory_module, "get_llm_client", lambda: mock_client)

    resp = client.get("/staff-directory/ai-summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is True
    assert body["narrative"] == "Fallback narrative without reasoning control."
    assert mock_client.create_message.call_count == 2
    assert "extra_body" not in mock_client.create_message.call_args.kwargs


def test_staff_ai_summary_unavailable_on_ai_failure(client, db_session, monkeypatch):
    staff_directory_module._STAFF_AI_SUMMARY_CACHE.clear()
    _create_staff(db_session)

    def _raise():
        raise ValueError("OPENROUTER_API_KEY environment variable not set.")

    monkeypatch.setattr(staff_directory_module, "get_llm_client", _raise)

    resp = client.get("/staff-directory/ai-summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is False
    assert body["narrative"] is None


def test_staff_ai_summary_prompt_reflects_loans_advances_payroll_and_term(client, db_session, monkeypatch):
    staff_directory_module._STAFF_AI_SUMMARY_CACHE.clear()
    today = date.today()

    active_staff = _create_staff(db_session, "Ngozi Williams", monthly_gross=150000.0)
    _create_staff(db_session, "Retired Teacher", monthly_gross=80000.0, is_active=False)

    loan = StaffLoan(staff_id=active_staff.id, employee_name=active_staff.full_name,
                      loan_amount=60000.0, deduction_start=today, is_active=True)
    db_session.add(loan)
    db_session.commit()
    db_session.add(StaffLoanPayment(loan_id=loan.id, amount_paid=10000.0, paid_date=today))
    db_session.commit()

    db_session.add(AdvancePayment(staff_id=active_staff.id, amount=20000.0, remaining_amount=20000.0,
                                   date_issued=today, is_recovered=False))
    db_session.add(PayrollEntry(staff_id=active_staff.id, period_year=today.year, period_month=today.month,
                                 gross_salary=150000.0, net_salary=150000.0, is_paid=True))
    db_session.add(Term(name="First Term", start_date=today - timedelta(days=5), end_date=today + timedelta(days=25)))
    db_session.commit()

    mock_client = MagicMock()
    mock_client.create_message.return_value = "narrative"
    monkeypatch.setattr(staff_directory_module, "get_llm_client", lambda: mock_client)

    resp = client.get("/staff-directory/ai-summary")
    assert resp.status_code == 200
    assert resp.json()["available"] is True

    prompt = mock_client.create_message.call_args.kwargs["messages"][0]["content"]
    assert "Active staff: 1" in prompt
    assert "Inactive staff: 1" in prompt
    assert "Total monthly gross payroll (active staff): ₦150,000.00" in prompt
    assert "Active staff loans: 1, total outstanding: ₦50,000.00" in prompt
    assert "Unrecovered salary advances (IOUs): 1, total outstanding: ₦20,000.00" in prompt
    assert "Payroll this month: 1 of 1 active staff paid" in prompt
    assert "Current term: First Term, 25 day(s) remaining" in prompt
