# FinanceAudit MCP server

Lets Claude work with your FinanceAudit app in plain English: look up transactions and payroll, and
(optionally) add, change and delete records. It talks to your existing API, so the app's own rules,
permissions and validation still apply.

- **Default: read-only.** Only lookup tools exist. Nothing can be changed.
- **Opt-in writes.** Set `MCP_ALLOW_WRITES=1` and 12 more tools appear: create / update / delete for
  transactions, staff, bonuses and bank accounts.
- **Deletes are two-step.** A delete does nothing until it is called again with `confirm=true`.
- **Account numbers are masked** (`******2765`) before they leave this process, including inside bank narrations.

---

## 1. Before you start

| You need | Notes |
|---|---|
| The API running | Local (`npx nx run api:serve`, default `http://localhost:8000`) or a staging URL |
| **A separate login for the server** | Create a user in the app with only the permissions you want Claude to have. Don't reuse your admin login. The server can do whatever that login can do |
| Python 3.10+ | Used only for this server; it has its own virtual environment |
| Claude Code or Claude Desktop | ChatGPT is not supported yet, see [section 7](#7-chatgpt-and-http-mode) |

> **Privacy:** every tool result is sent to the AI service you use. Try it against **staging or a local
> copy** first, not production, because results contain real staff names, amounts and descriptions.

## 2. Install (once)

```bash
cd apps/mcp
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## 3. Connect it to Claude

Use **absolute paths**. Below, `ROOT` means the folder that contains `apps/`, for example
`/Users/you/Personal-Project/Audit_app`.

### Claude Code (read-only)
```bash
claude mcp add financeaudit \
  -e FINANCEAUDIT_API_URL=http://localhost:8000 \
  -e FINANCEAUDIT_EMAIL=claude-bot@example.com \
  -e FINANCEAUDIT_PASSWORD='your-password' \
  -- ROOT/apps/mcp/.venv/bin/python ROOT/apps/mcp/server.py
```
Add `-s user` to make it available in every project, not just the current one.

### Claude Code with write tools
Add one more variable:
```bash
claude mcp add financeaudit-write \
  -e MCP_ALLOW_WRITES=1 \
  -e FINANCEAUDIT_API_URL=http://localhost:8000 \
  -e FINANCEAUDIT_EMAIL=claude-bot@example.com \
  -e FINANCEAUDIT_PASSWORD='your-password' \
  -- ROOT/apps/mcp/.venv/bin/python ROOT/apps/mcp/server.py
```
Tip: keep the read-only and write versions as **two separate entries** and only enable the write one
when you actually need to change something.

### Claude Desktop
Edit `claude_desktop_config.json` (Settings → Developer → Edit Config), then restart Claude Desktop:
```json
{
  "mcpServers": {
    "financeaudit": {
      "command": "ROOT/apps/mcp/.venv/bin/python",
      "args": ["ROOT/apps/mcp/server.py"],
      "env": {
        "FINANCEAUDIT_API_URL": "http://localhost:8000",
        "FINANCEAUDIT_EMAIL": "claude-bot@example.com",
        "FINANCEAUDIT_PASSWORD": "your-password",
        "MCP_ALLOW_WRITES": "1"
      }
    }
  }
}
```
Leave out `MCP_ALLOW_WRITES` for read-only.

### Check it works
In Claude Code run `claude mcp list` (it should show `financeaudit` as connected), then ask:
*"Use the financeaudit tools to tell me the next payroll month."*

## 4. What you can ask

### Read tools (always available)

| Tool | What it returns | Inputs |
|---|---|---|
| `list_transactions` | Transactions, newest first | `start_date`, `end_date`, `type` (income/expense), `category`, `vendor`, `limit` (max 200) |
| `transaction_summary` | Totals for a date range | `start_date`, `end_date` |
| `payroll_month` | Every staff line for a month: gross, bonus, deductions, net, paid or not, bank amount | `year`, `month` |
| `payroll_next_month` | The first month not fully processed | none |
| `list_staff` | Staff directory (masked account numbers) | `active_only` (default true) |
| `list_bonuses` | Bonus records | `staff_id`, `period_year`, `period_month` |
| `list_bank_accounts` | Bank accounts and balances (masked numbers) | none |

Example prompts:
- *"Show August 2026 payroll. Who is not paid yet?"*
- *"Total expenses by category for August 2026."*
- *"List Salary and Wages transactions between 1 and 31 August 2026."*
- *"Which active staff have no account number saved?"*
- *"What bonuses were recorded for July 2026?"*

### Write tools (only with `MCP_ALLOW_WRITES=1`)

| Tool | What it does | Inputs |
|---|---|---|
| `create_transaction` | Records a transaction | `date`, `type`, `amount`, `category`, `description`, optional `vendor`, `bank`, `bank_account_id` |
| `update_transaction` | Changes fields | `transaction_id`, `changes` (type, amount, currency, category, description, date, vendor, bank) |
| `delete_transaction` | Deletes one | `transaction_id`, `confirm` |
| `create_staff` | Adds a staff member | `full_name`, optional role, bank_name, account_number, monthly_gross, start_date, end_date, notes |
| `update_staff` | Changes fields | `staff_id`, `changes` (full_name, role, bank_name, account_number, monthly_gross, start_date, end_date, is_active, notes) |
| `delete_staff` | Deletes a staff member **and their payroll history** | `staff_id`, `confirm` |
| `create_bonus` | Adds a bonus record | `staff_id`, `bonus_type`, `percentage`, `basis_amount`, `frequency`, `period_year`, `period_month`, optional end/term/notes |
| `update_bonus` | Changes fields | `bonus_id`, `changes` |
| `delete_bonus` | Deletes a bonus record | `bonus_id`, `confirm` |
| `create_bank_account` | Adds a bank account | `bank_name`, optional holder, number, opening balance/date |
| `update_bank_account` | Changes fields | `account_id`, `changes` |
| `delete_bank_account` | Deletes one (the API refuses while transactions use it) | `account_id`, `confirm` |

Example prompts:
- *"Move transaction 2695 to the category Salary and Wages."* (look it up, change it)
- *"Deactivate staff 22 (they have left)."* (use this instead of deleting)
- *"Add a one-time ₦15,000 bonus for Ada Obi for August 2026."*
- *"Set Jonathan Ogogo's account number to 7038692765."*

**How a delete works.** You say *"delete transaction 3088"*. The tool replies *"Nothing was deleted…"*.
Claude should tell you what it is about to remove and ask. Only after you agree does it call again with
`confirm=true`. If Claude ever skips the question, refuse the tool approval prompt.

## 5. Safety, plainly

- **Writes are opt-in** and the server is read-only until you set `MCP_ALLOW_WRITES=1`.
- **Claude Code asks before each tool call** by default. Read what it is about to change before approving,
  and don't switch on "always allow" for the write tools.
- **The API still enforces its rules**: permissions of the login you gave the server, field validation, and
  refusals such as *"Cannot delete bank account with 3 linked transactions"*.
- **Audit log:** transaction changes are recorded by the API's audit log. **Staff, bonus and bank-account
  changes made through this server are not audit-logged**, so use a clearly named login (for example
  `claude-bot@…`) and keep an eye on what it did.
- **Updates are partial and checked.** For staff, bonuses and bank accounts the server reads the current
  record, changes only the fields you named, and sends it back. Unknown field names are rejected before
  anything is sent.
- **No bulk or irreversible shortcuts**: one record per delete, no "delete all".
- **Take a backup before a session with writes on production.** A restore point (for example a Neon branch)
  is the real undo button. Prefer staging.

## 6. What it cannot do (yet)

Process or reopen payroll, reconcile a payroll schedule (it needs a file upload), import bank statements,
and loans, advances, assets, inventory or tax records. Those stay in the app. Say if you want any added.

## 7. ChatGPT and HTTP mode

ChatGPT can only connect to a **public HTTPS** MCP URL and, as far as I know, its connector supports OAuth
or no authentication, not a static token. Supporting it would mean hosting this server and adding an OAuth
layer. That is not built, on purpose: the alternative is exposing financial data without proper
authentication. Check ChatGPT's current connector documentation before planning it.

For clients that just need a URL, there is an HTTP mode:
```bash
MCP_TRANSPORT=http MCP_BEARER_TOKEN='<long random string>' .venv/bin/python server.py
```
It serves `http://127.0.0.1:8765/mcp`; every request must send `Authorization: Bearer <token>`. It listens on
localhost only by default. Put it behind HTTPS before exposing it anywhere else.

## 8. Settings reference

| Variable | Default | Meaning |
|---|---|---|
| `FINANCEAUDIT_API_URL` | `http://localhost:8000` | Where the API is |
| `FINANCEAUDIT_EMAIL` / `FINANCEAUDIT_PASSWORD` | (required) | The server's own login |
| `MCP_ALLOW_WRITES` | off | `1` registers the 12 write tools |
| `MCP_TRANSPORT` | `stdio` | `http` to serve over HTTP |
| `MCP_BEARER_TOKEN` | (required for http) | Token every HTTP request must send |
| `MCP_HOST` / `MCP_PORT` | `127.0.0.1` / `8765` | HTTP bind address |

## 9. Troubleshooting

| You see | Cause and fix |
|---|---|
| `Set FINANCEAUDIT_EMAIL and FINANCEAUDIT_PASSWORD` | The two variables are missing from the config |
| `Login failed (401)` | Wrong email or password, or the user is inactive |
| `Login failed (429)` | The API allows 5 logins a minute. Wait a minute; the server reuses its token afterwards |
| `The API returned 403` | The server's login lacks permission for that section (staff, banking, transactions…). Give the role the permission, or use another login |
| Connection refused / timeout | The API is not running at `FINANCEAUDIT_API_URL` |
| No create/update/delete tools | `MCP_ALLOW_WRITES=1` is not set for the server you are using. Restart Claude after changing the config |
| Account numbers look like `******2765` | Intentional masking. The real number is never sent to Claude |
| `No module named 'mcp.server.fastmcp'` | A mismatched `mcp` version. Reinstall with `.venv/bin/pip install -r requirements.txt` (needs `mcp` 2.x) |
| Staff changes "didn't save" | Check `list_staff` afterwards; updates replace the whole record, so a stale name or id is the usual cause |

## 10. Tests

```bash
cd apps/mcp && .venv/bin/python -m pytest
```
26 tests cover login reuse, GET-only reads, masking, merge-on-update, the delete confirmation and the HTTP
token check. They use a fake API, so they never touch your data.
