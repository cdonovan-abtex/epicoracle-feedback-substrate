"""HTTP-domain observability event hook.

This module is deliberately parallel to ``events.py``. HTTP events are
high-volume request telemetry; feedback events are low-volume audit signals.
They do not share a sink slot.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from epicoracle_feedback.schemas.observability import HttpEvent

logger = logging.getLogger(__name__)

HttpEventSink = Callable[[HttpEvent], None]
__all__ = ["HttpEvent", "emit_http_event", "register_http_event_sink"]

_current_http_sink: HttpEventSink | None = None


def register_http_event_sink(sink: HttpEventSink | None) -> None:
    """Register or clear the process-wide HTTP-event sink."""
    global _current_http_sink  # noqa: PLW0603 -- process-wide hook registry by design
    if sink is not None and _current_http_sink is not None:
        logger.info(
            "epicoracle_feedback: replacing existing HTTP event sink (was %r, now %r)",
            _current_http_sink,
            sink,
        )
    _current_http_sink = sink


def emit_http_event(event: HttpEvent) -> None:
    """Dispatch an HTTP event, swallowing sink errors."""
    sink = _current_http_sink
    if sink is None:
        return
    try:
        sink(event)
    except Exception:  # noqa: BLE001 -- observability never breaks flow
        logger.warning(
            "epicoracle_feedback: HTTP event sink raised for %s; continuing",
            event.name,
            exc_info=True,
        )
