"""Payments API: a small service under test.

Accounts hold money in integer cents. Transfers move money between two accounts
of the same currency, require an Idempotency-Key header and write two ledger
entries (a debit and a credit) in one database transaction.
"""

import hashlib
import json
import os
import secrets
import sqlite3
import threading
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

DB_PATH = os.environ.get("DB_PATH", "data/payments.db")
API_USER = os.environ.get("API_USER", "tester")
API_PASSWORD = os.environ.get("API_PASSWORD", "demo-password")

Currency = Literal["PLN", "EUR"]
Amount = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2)]

_lock = threading.Lock()
_tokens: set[str] = set()


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


def _error(status: int, code: str, message: str, details=None) -> JSONResponse:
    body = {"error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    return JSONResponse(status_code=status, content=body)


async def _api_error(_: Request, exc: ApiError):
    return _error(exc.status, exc.code, exc.message)


async def _validation_error(_: Request, exc: RequestValidationError):
    details = [{"field": ".".join(str(p) for p in e["loc"][1:]), "problem": e["msg"]} for e in exc.errors()]
    return _error(422, "VALIDATION_ERROR", "Request is invalid", details)


# --- database ---------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    owner         TEXT    NOT NULL,
    currency      TEXT    NOT NULL,
    balance_cents INTEGER NOT NULL DEFAULT 0 CHECK (balance_cents >= 0),
    created_at    TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS transfers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    from_account_id INTEGER REFERENCES accounts(id),
    to_account_id   INTEGER NOT NULL REFERENCES accounts(id),
    amount_cents    INTEGER NOT NULL CHECK (amount_cents > 0),
    currency        TEXT    NOT NULL,
    idempotency_key TEXT    UNIQUE,
    request_hash    TEXT,
    created_at      TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS ledger_entries (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id   INTEGER NOT NULL REFERENCES accounts(id),
    transfer_id  INTEGER NOT NULL REFERENCES transfers(id),
    amount_cents INTEGER NOT NULL,
    created_at   TEXT    NOT NULL
);
"""


@contextmanager
def db():
    """One connection per request; writes are serialised with a lock."""
    conn = sqlite3.connect(DB_PATH, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


@asynccontextmanager
async def lifespan(_: FastAPI):
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    with db() as conn:
        conn.executescript(SCHEMA)
    yield


app = FastAPI(title="Payments API", version="1.0.0", lifespan=lifespan)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _to_cents(amount: Decimal) -> int:
    return int(amount * 100)


def _money(cents: int) -> str:
    return f"{Decimal(cents) / 100:.2f}"


# --- auth -------------------------------------------------------------------


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str
    password: str


@app.post("/auth/token", tags=["auth"])
def issue_token(creds: Credentials):
    if not (secrets.compare_digest(creds.username, API_USER) and secrets.compare_digest(creds.password, API_PASSWORD)):
        raise ApiError(401, "INVALID_CREDENTIALS", "Username or password is wrong")
    token = secrets.token_urlsafe(24)
    _tokens.add(token)
    return {"access_token": token, "token_type": "bearer"}


_bearer = HTTPBearer(auto_error=False)


def require_token(creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]):
    if creds is None or creds.credentials not in _tokens:
        raise ApiError(401, "UNAUTHORIZED", "A valid bearer token is required")


Auth = Depends(require_token)


# --- endpoints --------------------------------------------------------------


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}


class AccountIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    owner: str = Field(min_length=1, max_length=100)
    currency: Currency


def _account(conn, account_id: int) -> dict:
    row = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
    if row is None:
        raise ApiError(404, "ACCOUNT_NOT_FOUND", f"Account {account_id} does not exist")
    return {
        "id": row["id"],
        "owner": row["owner"],
        "currency": row["currency"],
        "balance": _money(row["balance_cents"]),
        "created_at": row["created_at"],
    }


@app.post("/accounts", status_code=201, dependencies=[Auth], tags=["accounts"])
def create_account(body: AccountIn):
    with _lock, db() as conn:
        cur = conn.execute(
            "INSERT INTO accounts (owner, currency, created_at) VALUES (?, ?, ?)", (body.owner, body.currency, _now())
        )
        return _account(conn, cur.lastrowid)


@app.get("/accounts/{account_id}", dependencies=[Auth], tags=["accounts"])
def get_account(account_id: int):
    with db() as conn:
        return _account(conn, account_id)


class DepositIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount: Amount


@app.post("/accounts/{account_id}/deposits", status_code=201, dependencies=[Auth], tags=["accounts"])
def deposit(account_id: int, body: DepositIn):
    cents = _to_cents(body.amount)
    with _lock, db() as conn:
        account = _account(conn, account_id)
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(
            "INSERT INTO transfers (from_account_id, to_account_id, amount_cents, currency, created_at)"
            " VALUES (NULL, ?, ?, ?, ?)",
            (account_id, cents, account["currency"], _now()),
        )
        conn.execute(
            "INSERT INTO ledger_entries (account_id, transfer_id, amount_cents, created_at) VALUES (?, ?, ?, ?)",
            (account_id, cur.lastrowid, cents, _now()),
        )
        conn.execute("UPDATE accounts SET balance_cents = balance_cents + ? WHERE id = ?", (cents, account_id))
        conn.execute("COMMIT")
        return _account(conn, account_id)


class TransferIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    from_account_id: int
    to_account_id: int
    amount: Amount
    currency: Currency


def _transfer(row) -> dict:
    return {
        "id": row["id"],
        "from_account_id": row["from_account_id"],
        "to_account_id": row["to_account_id"],
        "amount": _money(row["amount_cents"]),
        "currency": row["currency"],
        "created_at": row["created_at"],
    }


@app.post("/transfers", status_code=201, dependencies=[Auth], tags=["transfers"])
def create_transfer(body: TransferIn, idempotency_key: Annotated[str, Header(min_length=8, max_length=64)]):
    request_hash = hashlib.sha256(json.dumps(body.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()
    cents = _to_cents(body.amount)
    with _lock, db() as conn:
        previous = conn.execute("SELECT * FROM transfers WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
        if previous is not None:
            if previous["request_hash"] != request_hash:
                raise ApiError(409, "IDEMPOTENCY_KEY_REUSED", "This key was already used for a different request")
            return JSONResponse(status_code=200, content=_transfer(previous))

        if body.from_account_id == body.to_account_id:
            raise ApiError(422, "SAME_ACCOUNT", "Source and target account must differ")
        source = _account(conn, body.from_account_id)
        target = _account(conn, body.to_account_id)
        if not source["currency"] == target["currency"] == body.currency:
            raise ApiError(422, "CURRENCY_MISMATCH", "Both accounts must use the transfer currency")
        if _to_cents(Decimal(source["balance"])) < cents:
            raise ApiError(409, "INSUFFICIENT_FUNDS", "Source account balance is too low")

        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(
            "INSERT INTO transfers (from_account_id, to_account_id, amount_cents, currency, idempotency_key,"
            " request_hash, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (body.from_account_id, body.to_account_id, cents, body.currency, idempotency_key, request_hash, _now()),
        )
        transfer_id = cur.lastrowid
        for account_id, delta in ((body.from_account_id, -cents), (body.to_account_id, cents)):
            conn.execute(
                "INSERT INTO ledger_entries (account_id, transfer_id, amount_cents, created_at) VALUES (?, ?, ?, ?)",
                (account_id, transfer_id, delta, _now()),
            )
            conn.execute("UPDATE accounts SET balance_cents = balance_cents + ? WHERE id = ?", (delta, account_id))
        conn.execute("COMMIT")
        return _transfer(conn.execute("SELECT * FROM transfers WHERE id = ?", (transfer_id,)).fetchone())


@app.get("/accounts/{account_id}/transactions", dependencies=[Auth], tags=["accounts"])
def list_transactions(account_id: int):
    with db() as conn:
        _account(conn, account_id)
        rows = conn.execute(
            "SELECT transfer_id, amount_cents, created_at FROM ledger_entries WHERE account_id = ? ORDER BY id",
            (account_id,),
        ).fetchall()
        return [
            {"transfer_id": r["transfer_id"], "amount": _money(r["amount_cents"]), "created_at": r["created_at"]}
            for r in rows
        ]


app.add_exception_handler(ApiError, _api_error)
app.add_exception_handler(RequestValidationError, _validation_error)
