"""Checks the API cannot show on its own: what was actually written to the database."""

from decimal import Decimal


def cents(amount: str) -> int:
    return int(Decimal(amount) * 100)


def test_transfer_writes_one_debit_and_one_credit(api, new_account, db):
    source, target = new_account("40.00"), new_account()

    transfer_id = api.transfer(source.id, target.id, "12.34").json()["id"]

    rows = db.execute(
        "SELECT account_id, amount_cents FROM ledger_entries WHERE transfer_id = ? ORDER BY amount_cents",
        (transfer_id,),
    ).fetchall()
    assert rows == [(source.id, -1234), (target.id, 1234)]


def test_stored_balance_equals_sum_of_ledger_entries(api, new_account, db):
    a, b, c = new_account("100.00"), new_account("50.00"), new_account()
    api.transfer(a.id, b.id, "33.33")
    api.transfer(b.id, c.id, "50.01")
    api.transfer(c.id, a.id, "0.01")

    mismatches = db.execute(
        """
        SELECT a.id, a.balance_cents, COALESCE(SUM(l.amount_cents), 0) AS ledger_cents
        FROM accounts a LEFT JOIN ledger_entries l ON l.account_id = a.id
        WHERE a.id IN (?, ?, ?)
        GROUP BY a.id
        HAVING a.balance_cents <> ledger_cents
    """,
        (a.id, b.id, c.id),
    ).fetchall()
    assert mismatches == []


def test_transfers_between_accounts_conserve_money(api, new_account, db):
    a, b = new_account("20.00"), new_account("5.00")
    for amount in ("1.11", "2.22", "3.33"):
        api.transfer(a.id, b.id, amount)
    api.transfer(b.id, a.id, "4.44")

    total = db.execute("SELECT SUM(balance_cents) FROM accounts WHERE id IN (?, ?)", (a.id, b.id)).fetchone()[0]
    assert total == cents("25.00")


def test_rejected_transfer_leaves_no_rows(api, new_account, db):
    source, target = new_account("1.00"), new_account()
    before = db.execute("SELECT COUNT(*) FROM transfers").fetchone()[0]

    assert api.transfer(source.id, target.id, "1.01").status_code == 409

    assert db.execute("SELECT COUNT(*) FROM transfers").fetchone()[0] == before
    assert db.execute("SELECT COUNT(*) FROM ledger_entries WHERE account_id = ?", (target.id,)).fetchone()[0] == 0
