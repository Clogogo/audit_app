"""Chart of Accounts import, category mapping, Trial Balance, Profit & Loss and ledger endpoints."""
from datetime import date

from models import AccountMapping, BankAccount, ChartAccount, Transaction


def _tx(db, type_, amount, category, day="2026-08-10", description="desc", vendor="V", tx_type=None):
    tx = Transaction(type=tx_type or type_, amount=amount, currency="NGN", category=category, description=description,
                     date=date.fromisoformat(day), vendor=vendor)
    db.add(tx)
    db.commit()
    return tx


def _import(client):
    resp = client.post("/accounting/chart/import")
    assert resp.status_code == 200, resp.text
    return resp.json()


PERIOD = {"start_date": "2026-08-01", "end_date": "2026-08-31"}


def test_import_the_bundled_chart_then_list_it(client):
    assert client.get("/accounting/chart").json() == {"imported": False, "accounts": []}
    assert _import(client) == {"created": 240, "updated": 0, "total": 240}
    assert _import(client) == {"created": 0, "updated": 0, "total": 240}          # idempotent
    body = client.get("/accounting/chart").json()
    fees = next(a for a in body["accounts"] if a["code"] == "4.1.1.3.2")
    assert body["imported"] is True and fees["name"] == "Tuition & School Fees" and fees["is_postable"] is True
    assert next(a for a in body["accounts"] if a["code"] == "4.1.1.3")["is_postable"] is False


def test_import_accepts_an_uploaded_file_and_rejects_a_bad_one(client):
    bad = client.post("/accounting/chart/import", files={"file": ("x.csv", b"Name,Value\nA,1\n", "text/csv")})
    assert bad.status_code == 400 and "Account Code" in bad.json()["detail"]
    header = "Account Code,Account Name,Category,Statement Section,Normal Balance\n"
    ok = client.post("/accounting/chart/import", files={"file": ("x.csv", (header + "4.1,Sales,Income,Operating Revenue,Credit\n").encode(), "text/csv")})
    assert ok.status_code == 200 and ok.json()["total"] == 1


def test_mappings_list_every_category_in_use_with_its_suggestion(client, db_session):
    _tx(db_session, "income", 1000, "School Fees"); _tx(db_session, "income", 500, "School Fees")
    _tx(db_session, "expense", 200, "Books"); _tx(db_session, "expense", 50, "Mystery")
    body = client.get("/accounting/mappings").json()
    rows = {(r["category"], r["type"]): r for r in body["rows"]}
    assert body["chart_imported"] is False
    assert rows[("School Fees", "income")]["tx_count"] == 2 and rows[("School Fees", "income")]["total"] == 1500.0
    assert rows[("School Fees", "income")]["suggested_code"] == "4.1.1.3.2" and rows[("School Fees", "income")]["account_code"] is None
    assert rows[("Mystery", "expense")]["suggested_code"] is None


def test_setting_a_mapping_validates_the_account(client, db_session):
    _import(client)
    put = lambda code: client.put("/accounting/mappings", json={"category": "Books", "type": "expense", "account_code": code})
    assert put("5.1.1.1.2").status_code == 200
    assert db_session.query(AccountMapping).filter_by(category="Books", tx_type="expense").one().account_code == "5.1.1.1.2"
    assert put("9.9.9").status_code == 400                                        # no such account
    assert "group heading" in put("5.1.1.1").json()["detail"]                    # not postable
    assert put("5.1.1.3").status_code in (200, 400)                              # exists or not; never a 500
    assert put(None).status_code == 200                                          # clears it
    assert db_session.query(AccountMapping).count() == 0
    assert client.put("/accounting/mappings", json={"category": "Books", "type": "transfer", "account_code": None}).status_code == 422


def test_apply_suggestions_fills_only_unmapped_rows_and_only_valid_accounts(client, db_session):
    _import(client)
    _tx(db_session, "income", 100, "School Fees"); _tx(db_session, "expense", 40, "Books"); _tx(db_session, "expense", 5, "Mystery")
    client.put("/accounting/mappings", json={"category": "Books", "type": "expense", "account_code": "5.2.3.4"})   # user's own choice
    result = client.post("/accounting/mappings/apply-suggestions").json()
    assert result == {"applied": 1, "without_suggestion": 1}
    rows = {(r["category"], r["type"]): r["account_code"] for r in client.get("/accounting/mappings").json()["rows"]}
    assert rows == {("School Fees", "income"): "4.1.1.3.2", ("Books", "expense"): "5.2.3.4", ("Mystery", "expense"): None}


def test_apply_suggestions_needs_an_imported_chart(client, db_session):
    _tx(db_session, "income", 100, "School Fees")
    assert client.post("/accounting/mappings/apply-suggestions").json() == {"applied": 0, "without_suggestion": 1}


def _setup_books(client, db_session):
    _import(client)
    acct = BankAccount(bank_name="Test Bank", account_holder_name="Main", account_number="1", opening_balance=1000.0)
    db_session.add(acct); db_session.commit()
    _tx(db_session, "income", 5000, "School Fees", description="Fees ADA", vendor="PARENT")
    _tx(db_session, "expense", 2000, "Salary and Wages", description="August salary", vendor="ADA OBI")
    _tx(db_session, "expense", 300, "Mystery")
    _tx(db_session, "income", 9999, "School Fees", day="2026-09-05")                   # outside the period
    client.post("/accounting/mappings/apply-suggestions")


def test_profit_and_loss_comes_from_the_transactions(client, db_session):
    _setup_books(client, db_session)
    pl = client.get("/accounting/profit-and-loss", params=PERIOD).json()
    sections = {s["section"]: s for s in pl["sections"]}
    assert sections["Operating Revenue"]["accounts"] == [{"code": "4.1.1.3.2", "name": "Tuition & School Fees", "amount": 5000.0}]
    assert sections["Operating Expenses (OpEx)"]["total"] == 2000.0
    assert pl["unmapped_expense"] == 300.0 and pl["net_profit"] == 5000.0 - 2000.0 - 300.0
    assert pl["unmapped"] == [{"category": "Mystery", "type": "expense", "count": 1, "amount": 300.0}]
    assert (pl["start_date"], pl["end_date"]) == ("2026-08-01", "2026-08-31")


def test_trial_balance_balances_and_includes_the_banks_opening_balance(client, db_session):
    _setup_books(client, db_session)
    tb = client.get("/accounting/trial-balance", params=PERIOD).json()
    rows = {r["code"]: r for r in tb["rows"]}
    assert tb["balanced"] is True and tb["total_debit"] == tb["total_credit"]
    assert rows["1.2.4.1"]["debit"] == 1000 + 5000 - 2000 - 300                        # bank: opening + movements
    assert rows["B/F"]["credit"] == 1000.0 and rows["UNMAPPED-EXPENSE"]["debit"] == 300.0
    assert tb["unmapped"][0]["category"] == "Mystery"


def test_reports_work_before_any_chart_is_imported_and_ignore_other_transaction_types(client, db_session):
    _tx(db_session, "income", 100, "School Fees")
    _tx(db_session, "income", 777, "Internal Transfer", tx_type="transfer")
    pl = client.get("/accounting/profit-and-loss", params=PERIOD).json()
    assert pl["unmapped_income"] == 100.0 and pl["net_profit"] == 100.0
    assert client.get("/accounting/trial-balance", params=PERIOD).json()["balanced"] is True


def test_ledger_lists_the_transactions_behind_an_account_with_their_details(client, db_session):
    _setup_books(client, db_session)
    ledger = client.get("/accounting/ledger", params={**PERIOD, "account": "5.2.1.1.2"}).json()
    assert ledger["name"] == "Teaching & Academic Staff Costs" and ledger["total_debit"] == 2000.0
    assert [(r["description"], r["vendor"], r["debit"]) for r in ledger["rows"]] == [("August salary", "ADA OBI", 2000.0)]
    cash = client.get("/accounting/ledger", params={**PERIOD, "account": "1.2.4.1"}).json()
    assert cash["total_debit"] == 5000.0 and cash["total_credit"] == 2300.0


def test_date_range_must_be_valid(client):
    assert client.get("/accounting/profit-and-loss", params={"start_date": "2026-09-01", "end_date": "2026-08-01"}).status_code == 400
    assert client.get("/accounting/trial-balance").status_code == 422


def test_requires_the_tax_permission(anon_client):
    assert anon_client.get("/accounting/chart").status_code in (401, 403)
    assert anon_client.get("/accounting/profit-and-loss", params=PERIOD).status_code in (401, 403)


def test_the_bank_cannot_be_chosen_as_a_category_account(client):
    _import(client)
    resp = client.put("/accounting/mappings", json={"category": "Books", "type": "expense", "account_code": "1.2.4.1"})
    assert resp.status_code == 400 and "bank" in resp.json()["detail"]


def test_a_mapping_to_an_inactive_account_is_treated_as_unmapped(client, db_session):
    _import(client)
    _tx(db_session, "expense", 400, "Books")
    client.put("/accounting/mappings", json={"category": "Books", "type": "expense", "account_code": "5.1.1.1.2"})
    db_session.query(ChartAccount).filter_by(code="5.1.1.1.2").update({"status": "Inactive"})
    db_session.commit()
    pl = client.get("/accounting/profit-and-loss", params=PERIOD).json()
    assert pl["unmapped_expense"] == 400.0


def test_transfers_to_other_accounts_count_like_the_dashboard_and_vault_moves_do_not(client, db_session):
    _import(client)
    acct = BankAccount(bank_name="GTB", opening_balance=0.0)
    db_session.add(acct)
    db_session.commit()
    for desc, amount in (("Payment to supplier", 700), ("Auto-save to OWealth", 900)):
        tx = Transaction(type="transfer", amount=amount, currency="NGN", category="Other", description=desc,
                         date=date(2026, 8, 10), vendor="V", bank_account_id=acct.id)
        db_session.add(tx)
    db_session.commit()
    pl = client.get("/accounting/profit-and-loss", params=PERIOD).json()
    assert pl["unmapped_income"] + pl["unmapped_expense"] in (700.0,)   # only the supplier transfer, either direction


def test_ai_suggest_maps_only_unmapped_rows_with_valid_codes(client, db_session, monkeypatch):
    import ai_worker
    _import(client)
    _tx(db_session, "income", 100, "Zzz Fees"); _tx(db_session, "expense", 50, "Zzz Stuff"); _tx(db_session, "expense", 20, "Zzz Done")
    client.put("/accounting/mappings", json={"category": "Zzz Done", "type": "expense", "account_code": "5.1.1.1.2"})
    rows = {(r["category"], r["type"]): i for i, r in enumerate(client.get("/accounting/mappings").json()["rows"])}
    seen = {}
    def fake(prompt, *_):
        import json, re
        items = json.loads(re.search(r"Items:\n(\[.*\])", prompt).group(1))
        seen["n"] = len(items)
        by = {(x["category"], x["type"]): x["i"] for x in items}
        return json.dumps([{"i": by[("Zzz Fees", "income")], "code": "4.1.1.3.2"},
                           {"i": by[("Zzz Stuff", "expense")], "code": "1.2.4.1"}])   # cash is not allowed
    monkeypatch.setattr(ai_worker, "call_ai_text", fake)
    out = client.post("/accounting/mappings/ai-suggest")
    assert out.status_code == 200 and out.json()["applied"] == 1
    assert db_session.query(AccountMapping).filter_by(category="Zzz Fees", tx_type="income").one().account_code == "4.1.1.3.2"
    assert db_session.query(AccountMapping).filter_by(category="Zzz Stuff").count() == 0


def test_ai_suggest_reports_an_unavailable_ai(client, db_session, monkeypatch):
    import ai_worker
    _import(client)
    _tx(db_session, "expense", 50, "Zzz Stuff")
    monkeypatch.setattr(ai_worker, "call_ai_text", lambda p, *a: "")
    assert client.post("/accounting/mappings/ai-suggest").status_code == 503


def test_ai_suggest_replaces_a_stale_mapping_instead_of_failing(client, db_session, monkeypatch):
    import ai_worker
    _import(client)
    _tx(db_session, "expense", 50, "Zzz Stuff")
    client.put("/accounting/mappings", json={"category": "Zzz Stuff", "type": "expense", "account_code": "5.1.1.1.2"})
    db_session.query(ChartAccount).filter_by(code="5.1.1.1.2").update({"status": "Inactive"})
    db_session.commit()
    monkeypatch.setattr(ai_worker, "call_ai_text", lambda p, *a: '[{"i": 0, "code": "5.1.1.1.1"}]')
    out = client.post("/accounting/mappings/ai-suggest")
    assert out.status_code == 200 and out.json()["applied"] == 1
    assert db_session.query(AccountMapping).filter_by(category="Zzz Stuff").one().account_code == "5.1.1.1.1"


def test_ai_suggest_works_in_batches_and_keeps_what_succeeded(client, db_session, monkeypatch):
    import ai_worker
    import utils.account_suggestions as sug
    _import(client)
    for n in range(5):
        _tx(db_session, "expense", 10, f"Zzz {n}")
    monkeypatch.setattr(sug, "AI_BATCH", 2)
    calls = iter(['[{"i": 0, "code": "5.1.1.1.1"}, {"i": 1, "code": "5.1.1.1.1"}]'])
    monkeypatch.setattr(ai_worker, "call_ai_text", lambda p, *a: next(calls, "not json"))   # batches 2 and 3 fail (after their retry)
    out = client.post("/accounting/mappings/ai-suggest")
    assert out.status_code == 200 and out.json() == {"applied": 2, "without_suggestion": 3}


def test_ai_suggest_retries_an_empty_reply_and_accepts_a_code_followed_by_its_name(client, db_session, monkeypatch):
    import ai_worker
    _import(client)
    _tx(db_session, "expense", 50, "Zzz Stuff")
    replies = iter(["", '[{"i": 0, "code": "5.1.1.1.1 Some account name"}]'])
    seen = []
    monkeypatch.setattr(ai_worker, "call_ai_text", lambda p, *a: (seen.append(a), next(replies))[1])
    out = client.post("/accounting/mappings/ai-suggest")
    assert out.status_code == 200 and out.json()["applied"] == 1
    assert seen[0][0] >= 2000                                      # a budget big enough for reasoning models
