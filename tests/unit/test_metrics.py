from __future__ import annotations

from fastapi.testclient import TestClient

from backend.core.metrics import (
    kill_switch_activations_total,
    llm_calls_total,
    orders_submitted_total,
    tweets_ingested_total,
)


def test_metrics_endpoint_returns_prometheus_format(client: TestClient) -> None:
    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")


def test_defined_counters_appear_in_scrape(client: TestClient) -> None:
    body = client.get("/metrics").text
    for metric_name in (
        "xst_tweets_ingested_total",
        "xst_llm_calls_total",
        "xst_orders_submitted_total",
        "xst_kill_switch_activations_total",
        "xst_http_requests_total",
    ):
        assert metric_name in body, f"metric {metric_name} missing from /metrics"


def test_counter_increment_is_observable(client: TestClient) -> None:
    tweets_ingested_total.inc()
    llm_calls_total.labels(status="success").inc()
    orders_submitted_total.labels(mode="paper").inc()
    kill_switch_activations_total.labels(trigger="manual").inc()

    body = client.get("/metrics").text
    assert 'xst_llm_calls_total{status="success"}' in body
    assert 'xst_orders_submitted_total{mode="paper"}' in body
    assert 'xst_kill_switch_activations_total{trigger="manual"}' in body


def test_histograms_expose_buckets(client: TestClient) -> None:
    body = client.get("/metrics").text
    assert "xst_ingestion_to_decision_seconds_bucket" in body
    assert "xst_llm_latency_seconds_bucket" in body


def test_http_request_metrics_recorded_via_middleware(client: TestClient) -> None:
    client.get("/health")
    body = client.get("/metrics").text
    assert 'path="/health"' in body
    assert "xst_http_request_duration_seconds" in body


def test_metrics_endpoint_not_self_instrumented(client: TestClient) -> None:
    """/metrics scrape shouldn't show up in xst_http_requests_total."""
    client.get("/metrics")
    body = client.get("/metrics").text
    # If the path label for /metrics ever appears, grep will find it.
    assert 'xst_http_requests_total{method="GET",path="/metrics"' not in body
