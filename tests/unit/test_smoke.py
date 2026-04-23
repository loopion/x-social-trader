from fastapi.testclient import TestClient


def test_health_endpoint_returns_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_app_metadata(client: TestClient) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    info = response.json()["info"]
    assert info["title"] == "x-social-trader"
    assert info["version"] == "0.1.0"
