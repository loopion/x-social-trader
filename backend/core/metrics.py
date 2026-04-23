"""Prometheus metrics registry + declarations (OBS-03).

One shared `registry` owns every metric. Business metrics are declared here
with zero initial values — later phases just import and ``.inc()`` / ``.observe()``.
Metric names follow the ``xst_<namespace>_<unit>`` convention.
"""

from __future__ import annotations

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from prometheus_client.exposition import CONTENT_TYPE_LATEST

registry: CollectorRegistry = CollectorRegistry()

# --- Counters ----------------------------------------------------------------
tweets_ingested_total = Counter(
    "xst_tweets_ingested_total",
    "Tweets received from twitterapi.io and persisted.",
    registry=registry,
)
llm_calls_total = Counter(
    "xst_llm_calls_total",
    "LLM analyze() calls partitioned by status.",
    labelnames=("status",),
    registry=registry,
)
orders_submitted_total = Counter(
    "xst_orders_submitted_total",
    "Orders passed to the broker partitioned by trading mode.",
    labelnames=("mode",),
    registry=registry,
)
kill_switch_activations_total = Counter(
    "xst_kill_switch_activations_total",
    "Kill switch activations partitioned by trigger.",
    labelnames=("trigger",),
    registry=registry,
)

# HTTP request counter — emitted by the metrics middleware (MetricsMiddleware).
http_requests_total = Counter(
    "xst_http_requests_total",
    "HTTP requests served by the FastAPI app.",
    labelnames=("method", "path", "status"),
    registry=registry,
)

# --- Histograms --------------------------------------------------------------
_latency_buckets_slow = (0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0)
_latency_buckets_fast = (0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0)

ingestion_to_decision_seconds = Histogram(
    "xst_ingestion_to_decision_seconds",
    "Time from raw tweet receipt to LLM decision persisted.",
    buckets=_latency_buckets_slow,
    registry=registry,
)
decision_to_order_seconds = Histogram(
    "xst_decision_to_order_seconds",
    "Time from LLM decision to order submission.",
    buckets=_latency_buckets_slow,
    registry=registry,
)
llm_latency_seconds = Histogram(
    "xst_llm_latency_seconds",
    "LLMProvider.analyze() call duration.",
    buckets=_latency_buckets_slow,
    registry=registry,
)
broker_latency_seconds = Histogram(
    "xst_broker_latency_seconds",
    "BrokerProvider.place_order() call duration.",
    buckets=_latency_buckets_fast,
    registry=registry,
)
http_request_duration_seconds = Histogram(
    "xst_http_request_duration_seconds",
    "HTTP request duration served by the FastAPI app.",
    labelnames=("method", "path"),
    buckets=_latency_buckets_fast,
    registry=registry,
)

# --- Gauges ------------------------------------------------------------------
llm_cost_usd_daily = Gauge(
    "xst_llm_cost_usd_daily",
    "Cumulative LLM spend today (USD). Reset at midnight UTC.",
    registry=registry,
)
pnl_daily_usd = Gauge(
    "xst_pnl_daily_usd",
    "Daily realized P&L (USD).",
    registry=registry,
)
drawdown_pct = Gauge(
    "xst_drawdown_pct",
    "Drawdown from daily peak, percentage.",
    registry=registry,
)
open_positions = Gauge(
    "xst_open_positions",
    "Number of symbols with non-zero position.",
    registry=registry,
)


def render() -> tuple[bytes, str]:
    """Return (body, content_type) suitable for FastAPI ``Response``."""
    return generate_latest(registry), CONTENT_TYPE_LATEST
