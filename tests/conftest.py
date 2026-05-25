"""Shared fixtures for the epicoracle_feedback test suite.

Convention: every test isolates its JSONL fallback path via the ``inbox_path``
fixture (per-test ``tmp_path`` subdir) and the ``runner`` callable so no
test ever shells out to a real ``gh`` binary or touches a real GitHub repo.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from epicoracle_feedback import (
    FeedbackKind,
    FeedbackPayload,
    register_event_sink,
)


@pytest.fixture
def inbox_path(tmp_path: Path) -> Path:
    """Per-test JSONL fallback path so tests don't share state."""
    return tmp_path / "feedback_inbox.jsonl"


@pytest.fixture
def sample_payload() -> FeedbackPayload:
    """A canonical valid payload used by most dispatcher tests."""
    return FeedbackPayload(
        submission_id=uuid4(),
        subject="Tracking page errors when carrier code is blank",
        body="Repro: open /tracking, leave carrier empty, click Push. 500 toast.",
        kind=FeedbackKind.BUG,
        route_path="/tracking",
        satellite="marketplace",
        satellite_version="0.9.0",
        user_agent="Mozilla/5.0 (test)",
        submitted_by="operator-test@abtex.com",
        browser_timestamp="2026-05-25T12:00:00Z",
    )


@pytest.fixture(autouse=True)
def clear_event_sink() -> Any:
    """Ensure event sinks don't leak between tests."""
    register_event_sink(None)
    yield
    register_event_sink(None)


class FakeCompleted:
    """Stand-in for ``subprocess.CompletedProcess`` so tests don't have to
    construct the real type for every scenario."""

    def __init__(self, *, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@pytest.fixture
def fake_completed_factory() -> type[FakeCompleted]:
    """Expose the FakeCompleted class as a fixture."""
    return FakeCompleted
