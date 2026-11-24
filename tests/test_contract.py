"""The published OpenAPI document is part of the contract with API consumers."""

EXPECTED_OPERATIONS = {
    ("post", "/auth/token"),
    ("get", "/health"),
    ("post", "/accounts"),
    ("get", "/accounts/{account_id}"),
    ("post", "/accounts/{account_id}/deposits"),
    ("get", "/accounts/{account_id}/transactions"),
    ("post", "/transfers"),
}


def test_openapi_lists_exactly_the_expected_operations(anonymous):
    spec = anonymous.http.get("/openapi.json").json()

    operations = {(method, path) for path, item in spec["paths"].items() for method in item}
    assert operations == EXPECTED_OPERATIONS


def test_transfer_requires_idempotency_key_header_in_spec(anonymous):
    spec = anonymous.http.get("/openapi.json").json()

    parameters = spec["paths"]["/transfers"]["post"]["parameters"]
    header = next(p for p in parameters if p["in"] == "header")
    assert (header["name"].lower(), header["required"]) == ("idempotency-key", True)


def test_health_needs_no_token(anonymous):
    response = anonymous.http.get("/health")

    assert (response.status_code, response.json()) == (200, {"status": "ok"})
