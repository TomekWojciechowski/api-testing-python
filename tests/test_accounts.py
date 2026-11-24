import pytest

from tests.support.schemas import Account, Error, LedgerEntry


def test_new_account_starts_with_zero_balance(api):
    response = api.create_account("Anna Kowalska", "EUR")

    assert response.status_code == 201
    account = Account.model_validate(response.json())
    assert (account.owner, account.currency, account.balance) == ("Anna Kowalska", "EUR", "0.00")


def test_created_account_can_be_read_back(api, new_account):
    created = new_account()

    response = api.get_account(created.id)

    assert response.status_code == 200
    assert Account.model_validate(response.json()) == created


def test_unknown_account_returns_404(api):
    response = api.get_account(999_999)

    assert response.status_code == 404
    assert Error.model_validate(response.json()).error.code == "ACCOUNT_NOT_FOUND"


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"owner": "A", "currency": "USD"}, "currency"),
        ({"owner": "A", "currency": "pln"}, "currency"),
        ({"owner": "", "currency": "PLN"}, "owner"),
        ({"currency": "PLN"}, "owner"),
        ({"owner": "A", "currency": "PLN", "balance": "100.00"}, "balance"),
    ],
    ids=["unsupported-currency", "lower-case-currency", "empty-owner", "missing-owner", "client-sets-balance"],
)
def test_invalid_account_payload_is_rejected(api, body, field):
    response = api.http.post("/accounts", json=body)

    assert response.status_code == 422
    error = Error.model_validate(response.json()).error
    assert field in [d["field"] for d in error.details]


def test_deposit_increases_balance_and_is_listed(api, new_account):
    account = new_account()

    response = api.deposit(account.id, "150.25")

    assert response.status_code == 201
    assert Account.model_validate(response.json()).balance == "150.25"
    entries = [LedgerEntry.model_validate(e) for e in api.transactions(account.id).json()]
    assert [e.amount for e in entries] == ["150.25"]
