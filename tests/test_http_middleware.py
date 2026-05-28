from __future__ import annotations

import asyncio
import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from epicoracle_feedback.http_events import register_http_event_sink
from epicoracle_feedback.http_middleware import HttpLoggingMiddleware, dropped_events_counter
from epicoracle_feedback.schemas.observability import HttpEvent


def test_middleware_sink_failure_does_not_block_request(caplog) -> None:
    app = FastAPI()
    events: list[HttpEvent] = []

    @app.get("/items/{item_id}")
    def read_item(item_id: str) -> dict[str, str]:
        return {"item_id": item_id}

    def sink(event: HttpEvent) -> None:
        events.append(event)
        raise RuntimeError("store down")

    register_http_event_sink(sink)
    app.add_middleware(HttpLoggingMiddleware, tenant="pilot")
    try:
        with caplog.at_level(logging.WARNING), TestClient(app) as client:
            response = client.get("/items/123?secret=hidden")
    finally:
        register_http_event_sink(None)

    assert response.status_code == 200
    assert events[0].payload["route_template"] == "/items/{item_id}"
    assert "secret" not in events[0].payload["route_template"]
    assert "HTTP event sink raised" in caplog.text


def test_malformed_correlation_id_is_replaced() -> None:
    app = FastAPI()
    events: list[HttpEvent] = []

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"ok": "true"}

    register_http_event_sink(events.append)
    app.add_middleware(HttpLoggingMiddleware, tenant="pilot")
    try:
        with TestClient(app) as client:
            response = client.get("/health", headers={"X-Request-ID": "bad/value"})
    finally:
        register_http_event_sink(None)

    assert response.status_code == 200
    assert events[0].correlation_id != "bad/value"
    assert len(events[0].correlation_id) == 36


def test_queue_overflow_increments_counter_and_unblocks(caplog, monkeypatch) -> None:
    app = FastAPI()
    dropped_events_counter.reset()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"ok": "true"}

    app.add_middleware(HttpLoggingMiddleware, tenant="pilot", queue_size=1)
    with caplog.at_level(logging.WARNING), TestClient(app) as client:
        middleware = _find_middleware(app.middleware_stack)
        assert isinstance(middleware, HttpLoggingMiddleware)
        monkeypatch.setattr(
            middleware.queue,
            "put_nowait",
            lambda _event: (_ for _ in ()).throw(asyncio.QueueFull),
        )
        response = client.get("/health")

    assert response.status_code == 200
    assert dropped_events_counter.value == 1
    assert "queue full" in caplog.text


def _find_middleware(stack):
    current = stack
    while current is not None:
        if isinstance(current, HttpLoggingMiddleware):
            return current
        current = getattr(current, "app", None)
    return None
