"""The MCP server talks to the API only through GET requests, caches its login, and masks accounts.
Names, accounts and amounts are fictional."""
import asyncio
import json

import httpx
import pytest
from starlette.testclient import TestClient

import server


def make_api(routes, calls):
    """An Api wired to a fake backend; `routes` maps 'METHOD /path' to (status, json)."""
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        status, body = routes[f"{request.method} {request.url.path}"]
        return httpx.Response(status, json=body)
    return server.Api("http://api.test", "me@example.com", "pw", transport=httpx.MockTransport(handler))


@pytest.fixture
def calls():
    return []


def use(monkeypatch, routes, calls):
    routes.setdefault("POST /auth/login", (200, {"access_token": "tok-1", "token_type": "bearer"}))
    monkeypatch.setattr(server, "api", make_api(routes, calls))


def test_logs_in_once_and_reuses_the_token(monkeypatch, calls):
    use(monkeypatch, {"GET /payroll/next-month": (200, {"year": 2026, "month": 8})}, calls)
    server.payroll_next_month()
    server.payroll_next_month()
    assert [c.method for c in calls].count("POST") == 1
    assert all(c.headers["authorization"] == "Bearer tok-1" for c in calls if c.method == "GET")


def test_logs_in_again_once_when_the_token_expires(monkeypatch, calls):
    tokens = iter(["tok-1", "tok-2"])
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == "/auth/login":
            return httpx.Response(200, json={"access_token": next(tokens)})
        seen.append(request.headers["authorization"])
        return httpx.Response(401 if request.headers["authorization"] == "Bearer tok-1" else 200, json={"year": 2026, "month": 8})

    monkeypatch.setattr(server, "api", server.Api("http://api.test", "me@example.com", "pw", transport=httpx.MockTransport(handler)))
    assert server.payroll_next_month() == {"year": 2026, "month": 8}
    assert seen == ["Bearer tok-1", "Bearer tok-2"]


def test_only_ever_sends_gets_apart_from_the_login(monkeypatch, calls):
    use(monkeypatch, {
        "GET /transactions": (200, {"items": [], "total": 0}), "GET /transactions/summary": (200, {}),
        "GET /payroll/compute": (200, []), "GET /payroll/next-month": (200, {}), "GET /staff-directory/": (200, []),
        "GET /teacher-bonuses/": (200, []), "GET /bank-accounts": (200, []),
    }, calls)
    server.list_transactions(); server.transaction_summary(); server.payroll_month(2026, 8); server.payroll_next_month()
    server.list_staff(); server.list_bonuses(); server.list_bank_accounts()
    assert {c.method for c in calls if c.url.path != "/auth/login"} == {"GET"}


def test_list_transactions_sends_filters_drops_blanks_clamps_the_limit_and_masks_accounts(monkeypatch, calls):
    page = {"total": 1, "items": [{"id": 1, "description": "Transfer to ADA OBI | OPay | 7038692765 | August Salary"}]}
    use(monkeypatch, {"GET /transactions": (200, page)}, calls)
    from datetime import date
    out = server.list_transactions(start_date=date(2026, 8, 1), type="expense", category="Salary", limit=9999)
    query = dict(calls[-1].url.params)
    assert query == {"start_date": "2026-08-01", "type": "expense", "category": "Salary", "limit": "200"}
    assert out["items"][0]["description"] == "Transfer to ADA OBI | OPay | ******2765 | August Salary"


def test_staff_and_bank_account_numbers_are_masked(monkeypatch, calls):
    use(monkeypatch, {
        "GET /staff-directory/": (200, [{"full_name": "Ada Obi", "account_number": "0123456789"}, {"full_name": "No Acct", "account_number": None}]),
        "GET /bank-accounts": (200, [{"bank_name": "OPay", "account_number": "7038692765"}]),
    }, calls)
    assert [s["account_number"] for s in server.list_staff()] == ["******6789", None]
    assert server.list_bank_accounts()[0]["account_number"] == "******2765"
    assert dict(calls[-1].url.params) == {}


def test_payroll_month_passes_year_and_month(monkeypatch, calls):
    use(monkeypatch, {"GET /payroll/compute": (200, [{"full_name": "Ada Obi"}])}, calls)
    assert server.payroll_month(2026, 8) == [{"full_name": "Ada Obi"}]
    assert dict(calls[-1].url.params) == {"year": "2026", "month": "8"}


def test_clear_errors_without_credentials_or_when_the_api_refuses(monkeypatch, calls):
    monkeypatch.setattr(server, "api", server.Api("http://api.test", None, None))
    with pytest.raises(server.ApiError, match="FINANCEAUDIT_EMAIL"):
        server.payroll_next_month()
    use(monkeypatch, {"GET /bank-accounts": (403, {"detail": "no"})}, calls)
    with pytest.raises(server.ApiError, match="403"):
        server.list_bank_accounts()
    use(monkeypatch, {"POST /auth/login": (401, {"detail": "bad"})}, calls)
    with pytest.raises(server.ApiError, match="Login failed"):
        server.payroll_next_month()


def test_the_server_registers_exactly_the_read_only_tools():
    tools = asyncio.run(server.mcp.list_tools())
    assert sorted(t.name for t in tools) == sorted([
        "list_transactions", "transaction_summary", "payroll_month", "payroll_next_month",
        "list_staff", "list_bonuses", "list_bank_accounts",
    ])


def test_a_tool_works_through_the_server_layer(monkeypatch, calls):
    use(monkeypatch, {"GET /payroll/next-month": (200, {"year": 2026, "month": 8})}, calls)
    result = asyncio.run(server.mcp.call_tool("payroll_next_month", {}))
    assert "2026" in json.dumps(result, default=str)


def test_http_mode_requires_the_bearer_token():
    client = TestClient(server.build_http_app("s3cret"))
    assert client.get("/anything").status_code == 401
    assert client.get("/anything", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/anything", headers={"Authorization": "Bearer s3cret"}).status_code != 401


def test_http_mode_refuses_to_start_without_a_token(monkeypatch):
    monkeypatch.setenv("MCP_TRANSPORT", "http")
    monkeypatch.delenv("MCP_BEARER_TOKEN", raising=False)
    with pytest.raises(SystemExit, match="MCP_BEARER_TOKEN"):
        server.main()


def test_error_messages_reach_the_client_instead_of_a_generic_failure(monkeypatch):
    monkeypatch.setattr(server, "api", server.Api("http://api.test", None, None))
    with pytest.raises(server.ToolError, match="FINANCEAUDIT_EMAIL"):
        asyncio.run(server.mcp.call_tool("payroll_next_month", {}))


# ── write tools ───────────────────────────────────────────────────────────────

WRITE_NAMES = {
    "create_transaction", "update_transaction", "delete_transaction", "create_staff", "update_staff", "delete_staff",
    "create_bonus", "update_bonus", "delete_bonus", "create_bank_account", "update_bank_account", "delete_bank_account",
}
STAFF = {"id": 5, "full_name": "Ada Obi", "role": "Teacher", "bank_name": None, "account_number": "0123456789",
         "monthly_gross": 25000.0, "start_date": None, "end_date": None, "is_active": True, "notes": None,
         "created_at": "2026-01-01", "updated_at": "2026-01-01"}


def sent(calls, method):
    return [c for c in calls if c.method == method]


def test_writes_are_off_by_default_and_only_registered_on_request():
    from mcp.server.mcpserver import MCPServer
    assert server.ALLOW_WRITES is False
    assert not WRITE_NAMES & {t.name for t in asyncio.run(server.mcp.list_tools())}
    fresh = MCPServer("t")
    server.register_write_tools(fresh)
    assert {t.name for t in asyncio.run(fresh.list_tools())} == WRITE_NAMES


def test_create_transaction_posts_the_record(monkeypatch, calls):
    use(monkeypatch, {"POST /transactions": (201, {"id": 9})}, calls)
    from datetime import date
    assert server.create_transaction(date(2026, 8, 28), "expense", 15000.0, "Salary and Wages", "August salary", vendor="ADA OBI") == {"id": 9}
    assert json.loads(sent(calls, "POST")[-1].content) == {
        "date": "2026-08-28", "type": "expense", "amount": 15000.0, "category": "Salary and Wages",
        "description": "August salary", "vendor": "ADA OBI", "bank": None, "bank_account_id": None,
    }


def test_update_transaction_sends_only_the_requested_changes(monkeypatch, calls):
    use(monkeypatch, {"PUT /transactions/7": (200, {"id": 7})}, calls)
    server.update_transaction(7, {"category": "Books"})
    assert json.loads(sent(calls, "PUT")[0].content) == {"category": "Books"}


def test_updates_reject_unknown_or_empty_changes_without_calling_the_api(monkeypatch, calls):
    use(monkeypatch, {}, calls)
    with pytest.raises(server.ApiError, match="Not allowed: id"):
        server.update_transaction(7, {"id": 99, "category": "Books"})
    with pytest.raises(server.ApiError, match="at least one field"):
        server.update_staff(5, {})
    assert calls == []


def test_update_staff_keeps_every_other_field(monkeypatch, calls):
    use(monkeypatch, {"GET /staff-directory/": (200, [STAFF]), "PUT /staff-directory/5": (200, {"id": 5})}, calls)
    server.update_staff(5, {"is_active": False})
    body = json.loads(sent(calls, "PUT")[0].content)
    assert body["is_active"] is False
    assert body["full_name"] == "Ada Obi" and body["account_number"] == "0123456789" and body["monthly_gross"] == 25000.0
    assert "id" not in body and "created_at" not in body


def test_update_of_a_missing_record_is_a_clear_error(monkeypatch, calls):
    use(monkeypatch, {"GET /teacher-bonuses/": (200, [])}, calls)
    with pytest.raises(server.ApiError, match="Bonus 3 was not found"):
        server.update_bonus(3, {"notes": "x"})
    assert not sent(calls, "PUT")


def test_update_bonus_and_bank_account_round_trip(monkeypatch, calls):
    bonus = {"id": 3, "staff_id": 5, "bonus_type": "award", "percentage": 100.0, "basis_amount": 25000.0, "frequency": "onetime",
             "period_year": 2026, "period_month": 7, "end_year": None, "end_month": None, "term_id": None, "notes": None, "amount": 25000.0}
    bank = {"id": 2, "bank_name": "OPay", "account_holder_name": "School", "account_number": "7038692765", "opening_balance": 0.0,
            "opening_balance_date": None, "current_balance": 10.0}
    use(monkeypatch, {"GET /teacher-bonuses/": (200, [bonus]), "PUT /teacher-bonuses/3": (200, {}),
                      "GET /bank-accounts": (200, [bank]), "PUT /bank-accounts/2": (200, {})}, calls)
    server.update_bonus(3, {"percentage": 50})
    server.update_bank_account(2, {"account_holder_name": "Marvellous School"})
    puts = [json.loads(c.content) for c in sent(calls, "PUT")]
    assert puts[0]["percentage"] == 50 and puts[0]["basis_amount"] == 25000.0 and "amount" not in puts[0]
    assert puts[1]["account_holder_name"] == "Marvellous School" and puts[1]["account_number"] == "7038692765"


@pytest.mark.parametrize("call, routes", [
    (lambda: server.delete_transaction(7), {}),
    (lambda: server.delete_staff(5), {"GET /staff-directory/": (200, [STAFF])}),
    (lambda: server.delete_bonus(3), {"GET /teacher-bonuses/": (200, [{"id": 3, "staff_name": "Ada Obi", "bonus_type": "award", "amount": 1, "period_year": 2026, "period_month": 7}])}),
    (lambda: server.delete_bank_account(2), {"GET /bank-accounts": (200, [{"id": 2, "bank_name": "OPay", "account_holder_name": "School"}])}),
])
def test_delete_does_nothing_until_confirmed(monkeypatch, calls, call, routes):
    use(monkeypatch, dict(routes), calls)
    result = call()
    assert result["deleted"] is False and "confirm=true" in result["message"]
    assert not sent(calls, "DELETE")


def test_confirmed_delete_sends_the_delete_and_handles_an_empty_204(monkeypatch, calls):
    use(monkeypatch, {"DELETE /transactions/7": (204, None), "DELETE /teacher-bonuses/3": (204, None)}, calls)
    assert server.delete_transaction(7, confirm=True) == {"deleted": True, "id": 7}
    assert server.delete_bonus.__name__ == "delete_bonus"
    api = server.api
    assert api.request("DELETE", "/teacher-bonuses/3") is None
    assert [c.url.path for c in sent(calls, "DELETE")] == ["/transactions/7", "/teacher-bonuses/3"]


def test_staff_delete_preview_names_the_person_and_warns_about_payroll_history(monkeypatch, calls):
    use(monkeypatch, {"GET /staff-directory/": (200, [STAFF])}, calls)
    preview = server.delete_staff(5)
    assert preview["staff"]["full_name"] == "Ada Obi" and "is_active=false" in preview["warning"]


def test_the_apis_own_refusal_reason_is_passed_on(monkeypatch, calls):
    use(monkeypatch, {
        "GET /bank-accounts": (200, [{"id": 2, "bank_name": "OPay", "account_holder_name": None}]),
        "DELETE /bank-accounts/2": (400, {"detail": "Cannot delete bank account with 3 linked transactions."}),
    }, calls)
    with pytest.raises(server.ApiError, match="3 linked transactions"):
        server.delete_bank_account(2, confirm=True)


def test_write_results_mask_account_numbers_and_narrations():
    from server import _scrub
    assert _scrub({"id": 1, "account_number": "0123456789", "description": "To X | 7038692765"}) == {
        "id": 1, "account_number": "******6789", "description": "To X | ******2765"}
