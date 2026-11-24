"""Thin HTTP client for the Payments API. Tests assert on the returned responses."""

import uuid

import httpx


class PaymentsClient:
    def __init__(self, base_url: str, token: str | None = None):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self.http = httpx.Client(base_url=base_url, headers=headers, timeout=10)

    def close(self):
        self.http.close()

    def token(self, username: str, password: str) -> httpx.Response:
        return self.http.post("/auth/token", json={"username": username, "password": password})

    def create_account(self, owner: str = "Test Owner", currency: str = "PLN") -> httpx.Response:
        return self.http.post("/accounts", json={"owner": owner, "currency": currency})

    def get_account(self, account_id: int) -> httpx.Response:
        return self.http.get(f"/accounts/{account_id}")

    def deposit(self, account_id: int, amount: str) -> httpx.Response:
        return self.http.post(f"/accounts/{account_id}/deposits", json={"amount": amount})

    def transfer(
        self,
        from_id: int,
        to_id: int,
        amount: str,
        currency: str = "PLN",
        idempotency_key: str | None = None,
        send_key: bool = True,
    ) -> httpx.Response:
        headers = {}
        if send_key:
            headers["Idempotency-Key"] = idempotency_key or uuid.uuid4().hex
        body = {"from_account_id": from_id, "to_account_id": to_id, "amount": amount, "currency": currency}
        return self.http.post("/transfers", json=body, headers=headers)

    def transactions(self, account_id: int) -> httpx.Response:
        return self.http.get(f"/accounts/{account_id}/transactions")
