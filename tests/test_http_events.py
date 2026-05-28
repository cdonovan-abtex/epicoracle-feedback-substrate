from __future__ import annotations

import logging
from datetime import UTC, datetime

from epicoracle_feedback.http_events import emit_http_event, register_http_event_sink
from epicoracle_feedback.schemas.observability import HttpEvent


def test_http_event_sink_failure_is_logged_and_swallowed(caplog) -> None:
    def sink(_event: HttpEvent) -> None:
        raise RuntimeError("boom")

    register_http_event_sink(sink)
    try:
        with caplog.at_level(logging.WARNING):
            emit_http_event(
                HttpEvent(
                    name="http.request.completed",
                    correlation_id="abc-123",
                    timestamp_utc=datetime.now(UTC),
                )
            )
    finally:
        register_http_event_sink(None)

    assert "HTTP event sink raised" in caplog.text
