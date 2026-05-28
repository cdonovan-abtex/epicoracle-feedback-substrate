from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from epicoracle_feedback.schemas.observability import AccessLogEntry


def test_access_log_entry_rejects_naive_datetime() -> None:
    with pytest.raises(ValidationError):
        AccessLogEntry(
            correlation_id="abc-123",
            timestamp_utc=datetime(2026, 5, 27, 12, 0, 0),
            principal="operator@example.test",
            method="GET",
            route_template="/health",
            status=200,
            duration_ms=1,
            response_size_bytes=None,
            tenant="pilot",
            client_ip="127.0.0.1",
        )
