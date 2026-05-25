"""Structured-event hook for audit / observability.

Why this exists: the marketplace satellite has an existing audit-event
substrate. Codex's BLOCKER on the v0 brief flagged that replacing the
marketplace dispatcher with a shared package risked regressing that audit
trail — the package can't know each satellite's audit schema, but each
satellite needs to keep emitting its own.

Design: the package emits a typed ``FeedbackEvent`` at every state
transition. Satellites register a sink (a callable) at startup; the sink
adapts the structured event into the satellite's native audit format. If
no sink is registered, events are dropped (the dispatcher does not depend
on event delivery for correctness — it is observability, not control flow).

This is the Hook Pattern, not the Observer Pattern: one sink per process,
not a list. Satellites that need multi-sink fan-out compose their own
fan-out inside the registered callable. This keeps the substrate's
contract narrow.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


class FeedbackEvent(BaseModel):
    """One structured event in the feedback lifecycle.

    The ``name`` field uses dotted-namespaced strings — ``feedback.*`` for
    router/dispatcher events, ``agent.*`` for GH-Actions dispatch events.
    Names are case-sensitive; consumers can pattern-match by prefix.

    The ``payload`` field is intentionally untyped (``dict[str, Any]``) to
    avoid coupling the substrate to satellite-specific schemas. The v2
    brief enumerates the canonical event names + payload keys in its
    "Observability + correlation IDs" section.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(..., min_length=1, max_length=128)
    correlation_id: str = Field(..., min_length=1, max_length=64)
    submission_id: str | None = None
    payload: Mapping[str, Any] = Field(default_factory=dict)


EventSink = Callable[[FeedbackEvent], None]
"""Type alias for the sink callable. Synchronous on purpose — async event
emission inside the dispatcher's hot path would require us to plumb an
event loop reference through, and the marketplace satellite's audit
substrate is sync today anyway."""


_current_sink: EventSink | None = None


def register_event_sink(sink: EventSink | None) -> None:
    """Register the process-wide event sink.

    Call with ``None`` to clear (useful for tests). Calling more than once
    silently replaces the prior sink; we log at INFO so the replacement is
    visible in container startup logs.
    """
    global _current_sink  # noqa: PLW0603  -- intentional: process-wide hook registry
    if sink is not None and _current_sink is not None:
        logger.info(
            "epicoracle_feedback: replacing existing event sink "
            "(was %r, now %r)",
            _current_sink,
            sink,
        )
    _current_sink = sink


def emit_feedback_event(event: FeedbackEvent) -> None:
    """Dispatch an event to the registered sink, swallowing sink errors.

    Observability must never break control flow. If the sink raises, we
    log at WARNING and continue. Sinks that need stronger durability
    guarantees should buffer to disk themselves.
    """
    sink = _current_sink
    if sink is None:
        return
    try:
        sink(event)
    except Exception:  # noqa: BLE001  --  by design: observability never breaks flow
        logger.warning(
            "epicoracle_feedback: event sink raised for %s; continuing",
            event.name,
            exc_info=True,
        )
