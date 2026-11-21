"""MCP server for the FinanceAudit API.

By default it is READ-ONLY: only GET tools are registered. Set MCP_ALLOW_WRITES=1 to
also register create / update / delete tools for transactions, staff, bonuses and bank
accounts. Every write goes through the normal API, so its validation, permissions and
audit log apply; deletes do nothing until called again with confirm=true.
Account numbers are masked before they leave this process.
Run it over stdio for Claude Code / Claude Desktop (default), or over HTTP
(MCP_TRANSPORT=http, needs MCP_BEARER_TOKEN) for clients that need a URL.
"""
import hmac
import os
import re
import threading
from datetime import date
from typing import Any, Literal

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

ALLOW_WRITES = os.environ.get("MCP_ALLOW_WRITES") == "1"

mcp = MCPServer(
    "financeaudit",
    instructions=(
        "A school's finance app: bank transactions, payroll, staff, bonuses and bank accounts. "
        "Amounts are in naira. Account numbers are masked. "
        + (
            "You can also create, update and delete records. Before any write, tell the user exactly what will "
            "change and wait for their OK. Deletes need confirm=true after the user agrees."
            if ALLOW_WRITES else "It is read-only: it cannot change anything."
        )
    ),
)

MAX_ROWS = 200


class ApiError(ToolError):
    """A problem talking to the API; as a ToolError its message reaches the model instead of a generic failure."""


class Api:
    """GET-only client with a cached login token (the login is rate limited to 5/minute)."""

    def __init__(self, base_url: str, email: str | None, password: str | None, transport: httpx.BaseTransport | None = None):
        self._http = httpx.Client(base_url=base_url, timeout=30, transport=transport)
        self._email, self._password = email, password
        self._token: str | None = None
        self._lock = threading.Lock()  # tools may run on several threads; log in once, not once each

    def _login(self, stale: str | None = None) -> None:
        with self._lock:
            if self._token and self._token != stale:
                return  # another thread already refreshed it
            self._login_locked()

    def _login_locked(self) -> None:
        if not (self._email and self._password):
            raise ApiError("Set FINANCEAUDIT_EMAIL and FINANCEAUDIT_PASSWORD for the server.")
        reply = self._http.post("/auth/login", json={"email": self._email, "password": self._password})
        if reply.status_code != 200:
            raise ApiError(f"Login failed ({reply.status_code}); check FINANCEAUDIT_EMAIL / FINANCEAUDIT_PASSWORD.")
        self._token = reply.json()["access_token"]

    def request(self, method: str, path: str, body: dict[str, Any] | None = None, **params: Any) -> Any:
        query = {k: v for k, v in params.items() if v is not None}
        for attempt in (1, 2):
            token = self._token
            if not token:
                self._login()
                token = self._token
            reply = self._http.request(method, path, params=query, json=body, headers={"Authorization": f"Bearer {token}"})
            if reply.status_code == 401 and attempt == 1:
                with self._lock:
                    if self._token == token:
                        self._token = None  # expired: log in again once
                continue
            break
        if reply.status_code >= 400:
            try:
                detail = reply.json().get("detail")
            except ValueError:
                detail = None
            raise ApiError(f"The API returned {reply.status_code} for {path}." + (f" {detail}" if isinstance(detail, str) else ""))
        return reply.json() if reply.content else None

    def get(self, path: str, **params: Any) -> Any:
        return self.request("GET", path, **params)


api = Api(
    os.environ.get("FINANCEAUDIT_API_URL", "http://localhost:8000"),
    os.environ.get("FINANCEAUDIT_EMAIL"),
    os.environ.get("FINANCEAUDIT_PASSWORD"),
)


def _mask_account(value: str | None) -> str | None:
    return f"******{value[-4:]}" if value and len(value) > 4 else value


def _mask_digits(text: str | None) -> str | None:
    """Bank narrations carry account numbers ('Transfer to X | OPay | 7038692765 | note')."""
    return re.sub(r"\d{6,}", lambda m: "******" + m.group()[-4:], text) if text else text


def _scrub(record: Any) -> Any:
    """Mask a record returned by a write call the same way the read tools do."""
    if not isinstance(record, dict):
        return record
    out = {**record, "account_number": _mask_account(record["account_number"])} if "account_number" in record else dict(record)
    if isinstance(out.get("description"), str):
        out["description"] = _mask_digits(out["description"])
    return out


def _masked(rows: list[dict[str, Any]], field: str = "account_number") -> list[dict[str, Any]]:
    return [{**row, field: _mask_account(row.get(field))} for row in rows]


@mcp.tool()
def list_transactions(
    start_date: date | None = None,
    end_date: date | None = None,
    type: Literal["income", "expense"] | None = None,
    category: str | None = None,
    vendor: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """List bank/ledger transactions, newest first. Filter by date range, income/expense, category or vendor."""
    page = api.get(
        "/transactions",
        start_date=start_date.isoformat() if start_date else None,
        end_date=end_date.isoformat() if end_date else None,
        type=type, category=category, vendor=vendor, limit=min(max(limit, 1), MAX_ROWS),
    )
    return {**page, "items": [{**t, "description": _mask_digits(t.get("description"))} for t in page.get("items", [])]}


@mcp.tool()
def transaction_summary(start_date: date | None = None, end_date: date | None = None) -> Any:
    """Totals (income, expenses, balance, by category/month) for a date range."""
    return api.get(
        "/transactions/summary",
        start_date=start_date.isoformat() if start_date else None,
        end_date=end_date.isoformat() if end_date else None,
    )


@mcp.tool()
def payroll_month(year: int, month: int) -> Any:
    """Payroll lines for one month: gross, bonus, loan/advance/other deductions, net, whether paid, and the bank amount paid."""
    return api.get("/payroll/compute", year=year, month=month)


@mcp.tool()
def payroll_next_month() -> Any:
    """The first month whose payroll is not fully processed yet."""
    return api.get("/payroll/next-month")


@mcp.tool()
def list_staff(active_only: bool = True) -> list[dict[str, Any]]:
    """Staff directory (name, role, bank, masked account number, monthly gross, start/end dates, active)."""
    return _masked(api.get("/staff-directory/", active_only=active_only))


@mcp.tool()
def list_bonuses(staff_id: int | None = None, period_year: int | None = None, period_month: int | None = None) -> Any:
    """Bonus records (type, amount, frequency, period), optionally for one staff member or month."""
    return api.get("/teacher-bonuses/", staff_id=staff_id, period_year=period_year, period_month=period_month)


@mcp.tool()
def list_bank_accounts() -> list[dict[str, Any]]:
    """Bank accounts (bank, holder, masked account number, opening and current balance)."""
    return _masked(api.get("/bank-accounts"))


# ── Write tools (registered only when MCP_ALLOW_WRITES=1) ────────────────────

STAFF_FIELDS = {"full_name", "role", "bank_name", "account_number", "monthly_gross", "start_date", "end_date", "is_active", "notes"}
BONUS_FIELDS = {"staff_id", "bonus_type", "percentage", "basis_amount", "frequency", "period_year", "period_month",
                "end_year", "end_month", "term_id", "notes"}
BANK_FIELDS = {"bank_name", "account_holder_name", "account_number", "opening_balance", "opening_balance_date", "current_balance"}
TRANSACTION_FIELDS = {"type", "amount", "currency", "category", "description", "date", "vendor", "bank"}


def _allowed(changes: dict[str, Any], allowed: set[str]) -> dict[str, Any]:
    unknown = sorted(set(changes) - allowed)
    if unknown or not changes:
        raise ApiError(f"Give at least one field to change, from: {', '.join(sorted(allowed))}." + (f" Not allowed: {', '.join(unknown)}." if unknown else ""))
    return changes


def _find(path: str, record_id: int, what: str) -> dict[str, Any]:
    record = next((r for r in api.get(path) if r["id"] == record_id), None)
    if record is None:
        raise ApiError(f"{what} {record_id} was not found.")
    return record


def _update(path: str, record_id: int, what: str, changes: dict[str, Any], allowed: set[str], fields: set[str]) -> Any:
    """The API replaces whole records, so read the current one, apply only the requested changes, send it back."""
    changes = _allowed(changes, allowed)  # reject bad input before touching the API
    record = _find(path, record_id, what)
    return api.request("PUT", f"{path.rstrip('/')}/{record_id}", {**{k: record.get(k) for k in fields}, **changes})


def _delete(path: str, record_id: int, what: str, confirm: bool, preview: dict[str, Any]) -> dict[str, Any]:
    if not confirm:
        return {"deleted": False, "message": f"Nothing was deleted. To permanently delete {what} {record_id}, ask the user, then call again with confirm=true.", **preview}
    api.request("DELETE", f"{path.rstrip('/')}/{record_id}")
    return {"deleted": True, "id": record_id}


def create_transaction(
    date: date, type: Literal["income", "expense"], amount: float, category: str, description: str,
    vendor: str | None = None, bank: str | None = None, bank_account_id: int | None = None,
) -> Any:
    """Record a new transaction (amount in naira, positive). The API writes an audit-log entry."""
    return _scrub(api.request("POST", "/transactions", {
        "date": date.isoformat(), "type": type, "amount": amount, "category": category, "description": description,
        "vendor": vendor, "bank": bank, "bank_account_id": bank_account_id,
    }))


def update_transaction(transaction_id: int, changes: dict[str, Any]) -> Any:
    """Change fields of a transaction. `changes` may contain: type, amount, currency, category, description, date (YYYY-MM-DD), vendor, bank."""
    return _scrub(api.request("PUT", f"/transactions/{transaction_id}", _allowed(changes, TRANSACTION_FIELDS)))


def delete_transaction(transaction_id: int, confirm: bool = False) -> dict[str, Any]:
    """Permanently delete a transaction (the API logs the deletion). Does nothing unless confirm=true."""
    return _delete("/transactions", transaction_id, "transaction", confirm, {})


def create_staff(
    full_name: str, role: str | None = None, bank_name: str | None = None, account_number: str | None = None,
    monthly_gross: float = 0.0, start_date: date | None = None, end_date: date | None = None, notes: str | None = None,
) -> Any:
    """Add a staff member to the directory."""
    return _scrub(api.request("POST", "/staff-directory/", {
        "full_name": full_name, "role": role, "bank_name": bank_name, "account_number": account_number, "monthly_gross": monthly_gross,
        "start_date": start_date.isoformat() if start_date else None, "end_date": end_date.isoformat() if end_date else None, "notes": notes,
    }))


def update_staff(staff_id: int, changes: dict[str, Any]) -> Any:
    """Change a staff member. `changes` may contain: full_name, role, bank_name, account_number, monthly_gross, start_date, end_date, is_active, notes. To stop paying someone use is_active=false rather than deleting."""
    return _scrub(_update("/staff-directory/", staff_id, "Staff member", changes, STAFF_FIELDS, STAFF_FIELDS))


def delete_staff(staff_id: int, confirm: bool = False) -> dict[str, Any]:
    """Permanently delete a staff member AND their payroll history. Prefer update_staff with is_active=false. Does nothing unless confirm=true."""
    who = _find("/staff-directory/", staff_id, "Staff member")
    return _delete("/staff-directory/", staff_id, "staff member", confirm, {
        "staff": {"full_name": who["full_name"], "role": who.get("role"), "is_active": who.get("is_active")},
        "warning": "This also deletes their payroll history. To just stop paying them, use update_staff with is_active=false.",
    })


def create_bonus(
    staff_id: int, bonus_type: str, percentage: float, basis_amount: float, frequency: Literal["onetime", "monthly"],
    period_year: int, period_month: int, end_year: int | None = None, end_month: int | None = None,
    term_id: int | None = None, notes: str | None = None,
) -> Any:
    """Add a bonus record (bonus = percentage % of basis_amount; for a flat amount use the salary as basis and the matching percentage)."""
    return api.request("POST", "/teacher-bonuses/", {
        "staff_id": staff_id, "bonus_type": bonus_type, "percentage": percentage, "basis_amount": basis_amount, "frequency": frequency,
        "period_year": period_year, "period_month": period_month, "end_year": end_year, "end_month": end_month, "term_id": term_id, "notes": notes,
    })


def update_bonus(bonus_id: int, changes: dict[str, Any]) -> Any:
    """Change a bonus record. `changes` may contain: staff_id, bonus_type, percentage, basis_amount, frequency, period_year, period_month, end_year, end_month, term_id, notes."""
    return _update("/teacher-bonuses/", bonus_id, "Bonus", changes, BONUS_FIELDS, BONUS_FIELDS)


def delete_bonus(bonus_id: int, confirm: bool = False) -> dict[str, Any]:
    """Delete a bonus record (an unprocessed month stops including it). Does nothing unless confirm=true."""
    b = _find("/teacher-bonuses/", bonus_id, "Bonus")
    return _delete("/teacher-bonuses/", bonus_id, "bonus", confirm, {
        "bonus": {k: b.get(k) for k in ("staff_name", "bonus_type", "amount", "period_year", "period_month")},
    })


def create_bank_account(
    bank_name: str, account_holder_name: str | None = None, account_number: str | None = None,
    opening_balance: float | None = None, opening_balance_date: date | None = None,
) -> Any:
    """Add a bank account."""
    return _scrub(api.request("POST", "/bank-accounts", {
        "bank_name": bank_name, "account_holder_name": account_holder_name, "account_number": account_number,
        "opening_balance": opening_balance, "opening_balance_date": opening_balance_date.isoformat() if opening_balance_date else None,
    }))


def update_bank_account(account_id: int, changes: dict[str, Any]) -> Any:
    """Change a bank account. `changes` may contain: bank_name, account_holder_name, account_number, opening_balance, opening_balance_date, current_balance."""
    return _scrub(_update("/bank-accounts", account_id, "Bank account", changes, BANK_FIELDS, BANK_FIELDS))


def delete_bank_account(account_id: int, confirm: bool = False) -> dict[str, Any]:
    """Delete a bank account (the API refuses while transactions are linked to it). Does nothing unless confirm=true."""
    a = _find("/bank-accounts", account_id, "Bank account")
    return _delete("/bank-accounts", account_id, "bank account", confirm, {
        "bank_account": {"bank_name": a["bank_name"], "account_holder_name": a.get("account_holder_name")},
    })


WRITE_TOOLS = [
    create_transaction, update_transaction, delete_transaction,
    create_staff, update_staff, delete_staff,
    create_bonus, update_bonus, delete_bonus,
    create_bank_account, update_bank_account, delete_bank_account,
]


def register_write_tools(server: MCPServer) -> None:
    for tool in WRITE_TOOLS:
        server.tool()(tool)


if ALLOW_WRITES:
    register_write_tools(mcp)


class BearerAuth:
    """ASGI middleware: every HTTP request must carry `Authorization: Bearer <token>`."""

    def __init__(self, app: Any, token: str):
        self.app, self._expected = app, f"Bearer {token}".encode()

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] == "http":
            given = dict(scope["headers"]).get(b"authorization", b"")
            if not hmac.compare_digest(given, self._expected):
                await send({"type": "http.response.start", "status": 401, "headers": [(b"content-type", b"text/plain")]})
                await send({"type": "http.response.body", "body": b"Unauthorized"})
                return
        await self.app(scope, receive, send)  # lifespan etc. pass straight through


def build_http_app(token: str) -> BearerAuth:
    return BearerAuth(mcp.streamable_http_app(), token)


def main() -> None:
    if os.environ.get("MCP_TRANSPORT", "stdio") == "stdio":
        mcp.run()
        return
    token = os.environ.get("MCP_BEARER_TOKEN")
    if not token:
        raise SystemExit("Set MCP_BEARER_TOKEN to serve over HTTP.")
    import uvicorn
    # localhost only by default; put it behind HTTPS before exposing it anywhere else
    uvicorn.run(build_http_app(token), host=os.environ.get("MCP_HOST", "127.0.0.1"), port=int(os.environ.get("MCP_PORT", "8765")))


if __name__ == "__main__":
    main()
