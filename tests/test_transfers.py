import uuid

import pytest

from tests.support.schemas import Error, LedgerEntry, Transfer


def balance(api, account_id) -> str:
    return api.get_account(account_id).json()["balance"]


def test_transfer_moves_money_between_accounts(api, new_account):
    source, target = new_account("100.00"), new_account()

    response = api.transfer(source.id, target.id, "9.99")

    assert response.status_code == 201
    transfer = Transfer.model_validate(response.json())
    assert (transfer.from_account_id, transfer.to_account_id, transfer.amount) == (source.id, target.id, "9.99")
    assert balance(api, source.id) == "90.01"
    assert balance(api, target.id) == "9.99"


def test_transfer_appears_in_both_transaction_histories(api, new_account):
    source, target = new_account("50.00"), new_account()

    transfer_id = api.transfer(source.id, target.id, "20.00").json()["id"]

    source_entries = [LedgerEntry.model_validate(e) for e in api.transactions(source.id).json()]
    target_entries = [LedgerEntry.model_validate(e) for e in api.transactions(target.id).json()]
    assert (source_entries[-1].transfer_id, source_entries[-1].amount) == (transfer_id, "-20.00")
    assert (target_entries[-1].transfer_id, target_entries[-1].amount) == (transfer_id, "20.00")


@pytest.mark.parametrize("amount", ["0.29", "1.13", "4.35", "0.01"])
def test_amount_is_booked_to_the_exact_cent(api, new_account, amount):
    """These values have no exact binary float form: 0.29 * 100 == 28.999999999999996."""
    source, target = new_account("10.00"), new_account()

    response = api.transfer(source.id, target.id, amount)

    assert response.json()["amount"] == amount
    assert balance(api, target.id) == amount


def test_whole_balance_can_be_transferred(api, new_account):
    source, target = new_account("10.00"), new_account()

    assert api.transfer(source.id, target.id, "10.00").status_code == 201
    assert balance(api, source.id) == "0.00"


@pytest.mark.parametrize(
    "amount",
    ["0", "0.00", "-1.00", "1.001", "abc", "", "10000000000.00"],
    ids=["zero", "zero-cents", "negative", "three-decimals", "text", "empty", "too-large"],
)
def test_invalid_amount_is_rejected_and_nothing_moves(api, new_account, amount):
    source, target = new_account("100.00"), new_account()

    response = api.transfer(source.id, target.id, amount)

    assert response.status_code == 422
    assert Error.model_validate(response.json()).error.code == "VALIDATION_ERROR"
    assert (balance(api, source.id), balance(api, target.id)) == ("100.00", "0.00")


def test_insufficient_funds_are_rejected_without_side_effects(api, new_account):
    source, target = new_account("5.00"), new_account()

    response = api.transfer(source.id, target.id, "5.01")

    assert response.status_code == 409
    assert Error.model_validate(response.json()).error.code == "INSUFFICIENT_FUNDS"
    assert (balance(api, source.id), balance(api, target.id)) == ("5.00", "0.00")
    assert len(api.transactions(source.id).json()) == 1  # only the deposit


def test_transfer_to_same_account_is_rejected(api, new_account):
    account = new_account("10.00")

    response = api.transfer(account.id, account.id, "1.00")

    assert response.status_code == 422
    assert Error.model_validate(response.json()).error.code == "SAME_ACCOUNT"


@pytest.mark.parametrize(
    ("source_ccy", "target_ccy", "transfer_ccy"),
    [
        ("PLN", "EUR", "PLN"),
        ("PLN", "PLN", "EUR"),
    ],
    ids=["accounts-differ", "transfer-differs"],
)
def test_currency_mismatch_is_rejected(api, new_account, source_ccy, target_ccy, transfer_ccy):
    source, target = new_account("10.00", source_ccy), new_account(currency=target_ccy)

    response = api.transfer(source.id, target.id, "1.00", currency=transfer_ccy)

    assert response.status_code == 422
    assert Error.model_validate(response.json()).error.code == "CURRENCY_MISMATCH"


@pytest.mark.parametrize("unknown", ["source", "target"])
def test_unknown_account_returns_404(api, new_account, unknown):
    account = new_account("10.00")
    ids = (999_999, account.id) if unknown == "source" else (account.id, 999_999)

    response = api.transfer(*ids, "1.00")

    assert response.status_code == 404
    assert Error.model_validate(response.json()).error.code == "ACCOUNT_NOT_FOUND"


def test_missing_idempotency_key_is_rejected(api, new_account):
    source, target = new_account("10.00"), new_account()

    response = api.transfer(source.id, target.id, "1.00", send_key=False)

    assert response.status_code == 422
    assert "idempotency-key" in [d["field"] for d in Error.model_validate(response.json()).error.details]


def test_retry_with_same_key_does_not_charge_twice(api, new_account):
    source, target = new_account("100.00"), new_account()
    key = uuid.uuid4().hex

    first = api.transfer(source.id, target.id, "30.00", idempotency_key=key)
    retry = api.transfer(source.id, target.id, "30.00", idempotency_key=key)

    assert (first.status_code, retry.status_code) == (201, 200)
    assert retry.json() == first.json()
    assert balance(api, source.id) == "70.00"


def test_same_key_with_different_body_is_a_conflict(api, new_account):
    source, target = new_account("100.00"), new_account()
    key = uuid.uuid4().hex
    api.transfer(source.id, target.id, "30.00", idempotency_key=key)

    response = api.transfer(source.id, target.id, "31.00", idempotency_key=key)

    assert response.status_code == 409
    assert Error.model_validate(response.json()).error.code == "IDEMPOTENCY_KEY_REUSED"
    assert balance(api, source.id) == "70.00"
