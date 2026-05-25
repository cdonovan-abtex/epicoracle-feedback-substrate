"""Payload + result types for the feedback dispatcher.

These are frozen, validated dataclass-shaped types. ``FeedbackPayload`` uses
Pydantic so the boundary between the HTTP layer and the dispatcher cannot
silently accept malformed data (e.g. a string in place of a UUID), and so
the JSON-serialisation path going into the JSONL inbox is canonical.

Why client-generated ``submission_id``: the trinity-converged v2 brief
elevates idempotency to a BLOCKER. Both Codex and Gemini independently
identified the JSONL-replay double-create risk in v0; the only correct fix
is a client-generated identifier the server (and replay job) can use to
search GitHub before creating a new issue. See ``idempotency.check_idempotency``.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class FeedbackKind(StrEnum):
    """Strict enum mirroring the three-button modal in the operator UI.

    Free-form strings would defeat the label-routing convention used by the
    GitHub Actions classifier. Each variant maps 1:1 to a
    ``feedback/kind:<value>`` GitHub label.

    ``StrEnum`` (Python 3.11+) gives us the str-comparison semantics of the
    classic ``(str, Enum)`` pattern with a cleaner type narrowing.
    """

    BUG = "bug"
    SUGGESTION = "suggestion"
    QUESTION = "question"


class FeedbackPayload(BaseModel):
    """One feedback submission, validated at the FastAPI boundary and again
    here.

    The fields are split into three groups:

    * Operator-supplied (``subject``, ``body``, ``kind``).
    * Client-generated identifiers (``submission_id``, ``correlation_id``) —
      generated in the browser at submit time, persisted in localStorage so
      retries don't double-create issues.
    * Auto-captured context (``route_path``, ``user_agent``, etc.) — recorded
      by the router for triage in GitHub.

    Frozen so callers can pass payloads across thread or task boundaries
    without worrying about mid-flight mutation.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=False)

    # Identifiers (client-generated where possible for idempotency).
    submission_id: UUID = Field(
        ...,
        description=(
            "Client-generated UUIDv4 generated at modal-open time. The server "
            "trusts this for idempotency and uses it to search GitHub for a "
            "pre-existing issue before creating a new one."
        ),
    )
    correlation_id: UUID = Field(
        default_factory=uuid4,
        description=(
            "Cross-system correlation identifier. Defaults to a fresh UUIDv4 "
            "if the caller does not supply one. Threaded into all "
            "FeedbackEvent emissions so a single submission can be traced "
            "browser → issue → PR → deploy in one query."
        ),
    )

    # Operator-supplied fields.
    subject: str = Field(..., min_length=1, max_length=120)
    body: str = Field(..., min_length=1, max_length=5000)
    kind: FeedbackKind

    # Auto-captured context (router fills these in).
    route_path: str = Field(..., min_length=1, max_length=512)
    satellite: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Satellite slug — e.g. 'marketplace', 'compliance', 'hub'.",
    )
    satellite_version: str = Field(..., min_length=1, max_length=64)
    user_agent: str = Field("", max_length=512)
    submitted_by: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description=(
            "Actor identity — the principal email when auth is enabled, "
            "the literal string 'anonymous-operator' otherwise. The role "
            "identifier is allowed per the canonical 'no person names in "
            "code' convention."
        ),
    )
    browser_timestamp: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description=(
            "ISO 8601 timestamp from the browser. REQUIRED in v0.1 — was "
            "optional in v0 but the trinity flagged the diagnostic value of "
            "browser-clock-vs-server-clock skew."
        ),
    )


class FeedbackDispatchResult(BaseModel):
    """Outcome of one dispatch attempt.

    Exactly one of (``issue_url``, ``queued_offline=True``) is set on the
    success path. ``error`` is only populated on the fallback path and is
    intended for audit only — the operator never sees it (the modal renders
    the localized fallback message instead).

    On idempotency hit (the GitHub issue for this ``submission_id`` already
    exists), ``issue_url`` is set, ``queued_offline`` is False, and
    ``deduplicated`` is True.
    """

    model_config = ConfigDict(frozen=True)

    issue_url: str | None
    issue_number: int | None
    queued_offline: bool
    captured_at: str
    error: str | None = None
    deduplicated: bool = Field(
        default=False,
        description=(
            "True when this submission_id was found to already have an issue "
            "(idempotency hit). Counts as success — operator's submission is "
            "already in flight."
        ),
    )
