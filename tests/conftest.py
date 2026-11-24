"""Fixtures.

By default the suite starts the API with uvicorn on a free port and a fresh SQLite file.
Set API_BASE_URL (and DB_PATH for the database checks) to test an API that is already
running, for example the Docker container in CI.
"""

import os
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from tests.support.client import PaymentsClient
from tests.support.schemas import Account

ROOT = Path(__file__).resolve().parent.parent
USER = os.environ.get("API_USER", "tester")
PASSWORD = os.environ.get("API_PASSWORD", "demo-password")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_until_healthy(base_url: str, timeout: float = 20) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"{base_url}/health", timeout=1).status_code == 200:
                return
        except httpx.TransportError:
            pass
        time.sleep(0.2)
    # Stop the whole run once instead of reporting the same setup error for every test.
    pytest.exit(f"API at {base_url} did not become healthy within {timeout}s", returncode=3)


@pytest.fixture(scope="session")
def api_env(tmp_path_factory):
    """Yields (base_url, db_path). db_path is None when the database is not reachable."""
    if os.environ.get("API_BASE_URL"):
        base_url = os.environ["API_BASE_URL"].rstrip("/")
        _wait_until_healthy(base_url)
        yield base_url, os.environ.get("DB_PATH")
        return

    db_path = str(tmp_path_factory.mktemp("db") / "payments.db")
    port = _free_port()
    env = {**os.environ, "DB_PATH": db_path, "API_USER": USER, "API_PASSWORD": PASSWORD}
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port), "--log-level", "warning"],
        cwd=ROOT,
        env=env,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        _wait_until_healthy(base_url)
        yield base_url, db_path
    finally:
        server.terminate()
        server.wait(timeout=10)


@pytest.fixture(scope="session")
def base_url(api_env) -> str:
    return api_env[0]


@pytest.fixture(scope="session")
def token(base_url) -> str:
    response = PaymentsClient(base_url).token(USER, PASSWORD)
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


@pytest.fixture
def anonymous(base_url):
    client = PaymentsClient(base_url)
    yield client
    client.close()


@pytest.fixture
def api(base_url, token):
    client = PaymentsClient(base_url, token)
    yield client
    client.close()


@pytest.fixture
def new_account(api):
    """Factory: creates an account, optionally funded, and returns it as a validated model."""

    def create(balance: str | None = None, currency: str = "PLN", owner: str = "Test Owner") -> Account:
        response = api.create_account(owner, currency)
        assert response.status_code == 201, response.text
        account = Account.model_validate(response.json())
        if balance:
            funded = api.deposit(account.id, balance)
            assert funded.status_code == 201, funded.text
            account = Account.model_validate(funded.json())
        return account

    return create


@pytest.fixture
def db(api_env):
    """Read-only connection to the API's SQLite database, for checks the API itself cannot show."""
    db_path = api_env[1]
    if not db_path or not Path(db_path).exists():
        pytest.skip("Database file is not reachable from the test runner (set DB_PATH)")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    yield conn
    conn.close()
