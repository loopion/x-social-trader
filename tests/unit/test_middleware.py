"""RequestIDMiddleware + MetricsMiddleware behaviour."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.api.middleware import REQUEST_ID_HEADER


def test_generated_request_id_echoed_in_response(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    rid = response.headers.get(REQUEST_ID_HEADER)
    assert rid is not None
    assert len(rid) >= 8


def test_inbound_request_id_is_preserved(client: TestClient) -> None:
    response = client.get("/health", headers={REQUEST_ID_HEADER: "req-abc-123"})
    assert response.headers[REQUEST_ID_HEADER] == "req-abc-123"


def test_generated_request_ids_are_unique(client: TestClient) -> None:
    a = client.get("/health").headers[REQUEST_ID_HEADER]
    b = client.get("/health").headers[REQUEST_ID_HEADER]
    assert a != b
