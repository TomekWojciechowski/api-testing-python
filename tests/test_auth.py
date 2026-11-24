import pytest

from tests.conftest import PASSWORD, USER
from tests.support.client import PaymentsClient
from tests.support.schemas import Error, Token


def test_valid_credentials_return_bearer_token(anonymous):
    response = anonymous.token(USER, PASSWORD)

    assert response.status_code == 200
    Token.model_validate(response.json())


@pytest.mark.parametrize(
    ("username", "password"),
    [
        (USER, "wrong-password"),
        ("unknown-user", PASSWORD),
        ("", ""),
    ],
    ids=["wrong-password", "unknown-user", "empty"],
)
def test_invalid_credentials_are_rejected(anonymous, username, password):
    response = anonymous.token(username, password)

    assert response.status_code == 401
    assert Error.model_validate(response.json()).error.code == "INVALID_CREDENTIALS"


def test_protected_endpoint_requires_token(anonymous):
    response = anonymous.create_account()

    assert response.status_code == 401
    assert Error.model_validate(response.json()).error.code == "UNAUTHORIZED"


def test_unknown_token_is_rejected(base_url):
    client = PaymentsClient(base_url, token="not-a-real-token")

    response = client.get_account(1)

    assert response.status_code == 401


def test_token_endpoint_rejects_unexpected_fields(anonymous):
    response = anonymous.http.post("/auth/token", json={"username": USER, "password": PASSWORD, "role": "admin"})

    assert response.status_code == 422
    assert Error.model_validate(response.json()).error.code == "VALIDATION_ERROR"
