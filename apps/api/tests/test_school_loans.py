"""Tests for School Loan payment handling — specifically that a loan only
auto-closes (is_active -> False) once BOTH principal and the agreed
total_interest_due are paid, not principal alone."""


def _create_loan(client, total_interest_due: float = 0.0, loan_amount: float = 100000.0):
    resp = client.post("/school-loans/", json={
        "lender_name": "Test Cooperative",
        "loan_amount": loan_amount,
        "interest_rate": 10.0,
        "total_interest_due": total_interest_due,
        "collected_date": "2026-01-01",
    })
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_loan_with_no_interest_due_closes_on_principal_alone(client, db_session):
    # total_interest_due defaults to 0 -> unchanged legacy behavior.
    loan = _create_loan(client, total_interest_due=0.0)

    resp = client.post(f"/school-loans/{loan['id']}/payments", json={
        "amount_paid": 100000.0, "interest_amount": 0.0, "misc_amount": 0.0,
        "paid_date": "2026-02-01",
    })
    assert resp.status_code == 201, resp.text

    loan_after = client.get("/school-loans/").json()[0]
    assert loan_after["outstanding_today"] == 0.0
    assert loan_after["fully_paid"] is True
    assert loan_after["is_active"] is False


def test_loan_does_not_close_when_principal_paid_but_interest_still_owed(client, db_session):
    # ₦100,000 principal + ₦10,000 agreed interest. Paying only the principal
    # must NOT close the loan — this is the core bug being fixed.
    loan = _create_loan(client, total_interest_due=10000.0)

    resp = client.post(f"/school-loans/{loan['id']}/payments", json={
        "amount_paid": 100000.0, "interest_amount": 0.0, "misc_amount": 0.0,
        "paid_date": "2026-02-01",
    })
    assert resp.status_code == 201, resp.text

    loan_after = client.get("/school-loans/").json()[0]
    assert loan_after["outstanding_today"] == 0.0       # principal cleared
    assert loan_after["outstanding_interest"] == 10000.0  # interest still owed
    assert loan_after["fully_paid"] is False
    assert loan_after["is_active"] is True              # must still be open


def test_loan_closes_only_after_both_principal_and_interest_are_paid(client, db_session):
    loan = _create_loan(client, total_interest_due=10000.0)

    # First payment: principal only.
    resp = client.post(f"/school-loans/{loan['id']}/payments", json={
        "amount_paid": 100000.0, "interest_amount": 0.0, "misc_amount": 0.0,
        "paid_date": "2026-02-01",
    })
    assert resp.status_code == 201
    assert client.get("/school-loans/").json()[0]["is_active"] is True

    # Second payment: the remaining interest.
    resp = client.post(f"/school-loans/{loan['id']}/payments", json={
        "amount_paid": 10000.0, "interest_amount": 10000.0, "misc_amount": 0.0,
        "paid_date": "2026-03-01",
    })
    assert resp.status_code == 201

    loan_after = client.get("/school-loans/").json()[0]
    assert loan_after["outstanding_interest"] == 0.0
    assert loan_after["fully_paid"] is True
    assert loan_after["is_active"] is False


def test_editing_a_payment_reopens_a_loan_that_no_longer_qualifies_as_fully_paid(client, db_session):
    # Regression guard: previously only add_payment ever touched is_active,
    # so editing a payment down (e.g. correcting a data-entry mistake) left a
    # fully-repaid loan incorrectly marked closed.
    loan = _create_loan(client, total_interest_due=0.0)

    resp = client.post(f"/school-loans/{loan['id']}/payments", json={
        "amount_paid": 100000.0, "interest_amount": 0.0, "misc_amount": 0.0,
        "paid_date": "2026-02-01",
    })
    payment_id = resp.json()["id"]
    assert client.get("/school-loans/").json()[0]["is_active"] is False

    # Correcting the payment down to a partial amount must reopen the loan.
    resp = client.put(f"/school-loans/{loan['id']}/payments/{payment_id}", json={
        "amount_paid": 60000.0, "interest_amount": 0.0, "misc_amount": 0.0,
        "paid_date": "2026-02-01",
    })
    assert resp.status_code == 200, resp.text

    loan_after = client.get("/school-loans/").json()[0]
    assert loan_after["outstanding_today"] == 40000.0
    assert loan_after["is_active"] is True


def test_deleting_the_closing_payment_reopens_the_loan(client, db_session):
    loan = _create_loan(client, total_interest_due=0.0)

    resp = client.post(f"/school-loans/{loan['id']}/payments", json={
        "amount_paid": 100000.0, "interest_amount": 0.0, "misc_amount": 0.0,
        "paid_date": "2026-02-01",
    })
    payment_id = resp.json()["id"]
    assert client.get("/school-loans/").json()[0]["is_active"] is False

    resp = client.delete(f"/school-loans/{loan['id']}/payments/{payment_id}")
    assert resp.status_code == 204

    loan_after = client.get("/school-loans/").json()[0]
    assert loan_after["outstanding_today"] == 100000.0
    assert loan_after["is_active"] is True


def _update_loan(client, loan, **overrides):
    body = {
        "lender_name": loan["lender_name"],
        "loan_amount": loan["loan_amount"],
        "interest_rate": loan["interest_rate"],
        "total_interest_due": loan["total_interest_due"],
        "collected_date": loan["collected_date"],
        "notes": loan["notes"],
        "is_active": loan["is_active"],
    }
    body.update(overrides)
    return client.put(f"/school-loans/{loan['id']}", json=body)


def test_raising_total_interest_due_on_a_closed_loan_reopens_it(client, db_session):
    # Regression guard: editing loan terms (not a payment) can also make a
    # previously fully-paid loan incomplete again.
    loan = _create_loan(client, total_interest_due=0.0)
    client.post(f"/school-loans/{loan['id']}/payments", json={
        "amount_paid": 100000.0, "interest_amount": 0.0, "misc_amount": 0.0,
        "paid_date": "2026-02-01",
    })
    loan = client.get("/school-loans/").json()[0]
    assert loan["is_active"] is False

    resp = _update_loan(client, loan, total_interest_due=5000.0, is_active=False)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Money is still owed (the new interest) — can't stay closed even though
    # the request explicitly asked for is_active=False.
    assert body["outstanding_interest"] == 5000.0
    assert body["is_active"] is True


def test_explicit_is_active_is_respected_when_loan_is_genuinely_fully_paid(client, db_session):
    loan = _create_loan(client, total_interest_due=0.0)
    client.post(f"/school-loans/{loan['id']}/payments", json={
        "amount_paid": 100000.0, "interest_amount": 0.0, "misc_amount": 0.0,
        "paid_date": "2026-02-01",
    })
    loan = client.get("/school-loans/").json()[0]
    assert loan["is_active"] is False

    # Fully paid already — the user's explicit choice to reopen it for
    # tracking purposes must be respected, not silently overwritten.
    resp = _update_loan(client, loan, is_active=True)
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_active"] is True
