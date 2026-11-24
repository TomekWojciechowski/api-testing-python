"""Response contracts. extra="forbid" makes a test fail when the API adds or renames a field."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Money = Field(pattern=r"^-?\d+\.\d{2}$")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Token(Strict):
    access_token: str = Field(min_length=20)
    token_type: Literal["bearer"]


class Account(Strict):
    id: int
    owner: str
    currency: Literal["PLN", "EUR"]
    balance: str = Money
    created_at: str


class Transfer(Strict):
    id: int
    from_account_id: int | None
    to_account_id: int
    amount: str = Money
    currency: Literal["PLN", "EUR"]
    created_at: str


class LedgerEntry(Strict):
    transfer_id: int
    amount: str = Money
    created_at: str


class ErrorBody(Strict):
    code: str
    message: str
    details: list[dict] | None = None


class Error(Strict):
    error: ErrorBody
