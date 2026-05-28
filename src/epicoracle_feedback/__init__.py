"""epicoracle_feedback — shared operator-feedback substrate.

Public API. Satellites and the hub import from here; everything else under
``epicoracle_feedback`` is implementation detail and subject to change.

See the repo README for runbook, rollback, and security posture.
"""

from __future__ import annotations

from epicoracle_feedback.auth import resolve_gh_token
from epicoracle_feedback.credentials import scan_for_credentials
from epicoracle_feedback.dispatch import (
    DEFAULT_INBOX_PATH,
    DEFAULT_LABELS,
    GH_TIMEOUT_S,
    dispatch_feedback,
)
from epicoracle_feedback.events import (
    FeedbackEvent,
    emit_feedback_event,
    register_event_sink,
)
from epicoracle_feedback.http_events import (
    HttpEvent,
    emit_http_event,
    register_http_event_sink,
)
from epicoracle_feedback.idempotency import check_idempotency
from epicoracle_feedback.payload import (
    FeedbackDispatchResult,
    FeedbackKind,
    FeedbackPayload,
)

__version__ = "0.2.0"

__all__ = [
    "DEFAULT_INBOX_PATH",
    "DEFAULT_LABELS",
    "GH_TIMEOUT_S",
    "FeedbackDispatchResult",
    "FeedbackEvent",
    "FeedbackKind",
    "FeedbackPayload",
    "HttpEvent",
    "__version__",
    "check_idempotency",
    "dispatch_feedback",
    "emit_feedback_event",
    "emit_http_event",
    "register_event_sink",
    "register_http_event_sink",
    "resolve_gh_token",
    "scan_for_credentials",
]
