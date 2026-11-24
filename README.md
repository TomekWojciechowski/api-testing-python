# API testing in Python

[![API tests](https://github.com/TomekWojciechowski/api-testing-python/actions/workflows/tests.yml/badge.svg)](https://github.com/TomekWojciechowski/api-testing-python/actions/workflows/tests.yml)

API test automation with **pytest** and **httpx** for a small payments service. The tests check status codes and also response contracts, business rules, idempotent retries and what the service actually wrote to its **SQL database**. In CI, the service runs in **Docker** and the tests call it over HTTP, the same way they would call a test environment.

## What is tested

| Area | Examples |
|---|---|
| Authentication | Bearer token issued for valid credentials; 401 for wrong password, unknown user, missing or unknown token |
| Response contract | Every response is validated against a strict Pydantic model, so an added, renamed or retyped field fails the test. The OpenAPI document must list exactly the expected operations |
| Input validation | Data-driven negative tests: zero, negative, three-decimal, non-numeric and oversized amounts; unsupported currency; unexpected fields such as a client-supplied balance |
| Business rules | Insufficient funds (409), transfer to the same account, currency mismatch, unknown source or target account (404) |
| Money handling | Amounts such as 0.29 and 1.13, which have no exact binary float form, are booked to the exact cent |
| Idempotency | A retry with the same `Idempotency-Key` returns the original transfer and charges once; the same key with a different body is a 409 conflict |
| Database consistency | SQL checks on the SQLite file: one debit and one credit per transfer, stored balance equals the sum of ledger entries, money is conserved, a rejected transfer writes no rows |
| Side effects | Every rejected request is followed by a check that no balance changed |

46 tests run in about two seconds.

## How I checked that the tests catch bugs

A test suite that never fails proves little. I introduced bugs into the service one at a time and confirmed that the suite went red each time:

| Bug introduced | Tests that failed |
|---|---|
| Balance check removed | 2 (insufficient funds, no side effects) |
| Credit booked 1 cent too high | 4 (balances, ledger, money conservation) |
| Idempotency check removed | 2 (double charge, key reuse) |
| Amount converted with `float` instead of `Decimal` | 3 (0.29, 1.13 and 4.35 booked 1 cent too low) |
| Response field renamed | 26 (contract validation) |

## Project structure

```
app/main.py                    the service under test (FastAPI, SQLite)
tests/
├── conftest.py                starts the API or uses API_BASE_URL; token, client and account fixtures
├── support/client.py          thin HTTP client, one method per endpoint
├── support/schemas.py         response contracts (Pydantic, extra fields forbidden)
├── test_auth.py
├── test_accounts.py
├── test_transfers.py
├── test_contract.py           OpenAPI checks
└── test_database_consistency.py
scripts/summary.py             JUnit XML to GitHub Actions job summary
```

### Design decisions

- **Tests talk HTTP only.** The suite never imports the application code, so the same tests can run against a container or a deployed test environment by setting `API_BASE_URL`.
- **Database checks are read-only and optional.** They open the SQLite file in read-only mode and are skipped when `DB_PATH` is not reachable, for example against a remote environment.
- **Each test creates its own accounts.** Tests do not depend on each other or on run order and leave no shared state behind.
- **Money is a string with two decimals in the API and integer cents in the database.** The tests compare exact strings, not floats.
- **A broken environment stops the run once.** If the API is not healthy, pytest exits with one clear message instead of 46 identical setup errors.

## Run it

Requirements: Python 3.12 or newer.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest
```

Without `API_BASE_URL`, the suite starts the API itself with uvicorn on a free port and a fresh database.

### Against the Docker container (as in CI)

```bash
docker compose up --build --detach --wait
API_BASE_URL=http://localhost:8000 DB_PATH=data/payments.db pytest --html=reports/report.html --self-contained-html
docker compose down
```

## CI

GitHub Actions runs two jobs on every push and pull request:

1. **lint**: `ruff check` and `ruff format --check`
2. **API tests**: builds and starts the container, waits for its health check, runs the suite, writes a pass/fail table to the job summary and uploads the HTML and JUnit reports as an artifact. Container logs are printed when a test fails.

## About the service

The payments API in `app/` is a deliberately small service I wrote to have something realistic to test: accounts in PLN or EUR, deposits, transfers with an idempotency key, and a ledger with one entry per account movement. The demo credentials (`tester` / `demo-password`) are not secrets.

## Author

Tomasz Wojciechowski, Test Automation Engineer (Python, Java, SQL). [LinkedIn](https://www.linkedin.com/in/tomasz-wojciechowski-68a39a268/)
