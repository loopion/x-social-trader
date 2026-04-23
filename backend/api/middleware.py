"""Request-ID + Prometheus middleware (OBS-01 + OBS-03)."""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from backend.core.metrics import http_request_duration_seconds, http_requests_total

REQUEST_ID_HEADER = "X-Request-ID"


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Propagate `request_id` into structlog context and response headers."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex[:16]
        with structlog.contextvars.bound_contextvars(request_id=request_id):
            response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response


class MetricsMiddleware(BaseHTTPMiddleware):
    """Emit `xst_http_requests_total` and `xst_http_request_duration_seconds`.

    Uses `request.scope["route"].path` for the label so parameterised routes
    (``/orders/{id}``) don't explode cardinality. Excludes `/metrics` itself to
    avoid self-recursion in Prometheus scraping.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - start

        route = request.scope.get("route")
        path = getattr(route, "path", request.url.path)
        if path == "/metrics":
            return response

        http_requests_total.labels(
            method=request.method,
            path=path,
            status=str(response.status_code),
        ).inc()
        http_request_duration_seconds.labels(method=request.method, path=path).observe(elapsed)
        return response
