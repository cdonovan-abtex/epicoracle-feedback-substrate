"""Tests for scripts/agent-dispatch/answer_draft.py.

The script makes a real Anthropic API call in production; tests mock the
client so they're fast + offline + deterministic. Coverage:

  - graceful skip when ANTHROPIC_API_KEY is unset (existing v0.1.1 behavior)
  - happy path: question-kind issue → parse → wrap → Claude → comment + label
  - error paths: missing env, non-question kind, API error, empty response,
    non-substrate issue body — none crash the workflow; all transition to
    needs-human + post diagnostic comment
"""

from __future__ import annotations

import json
import pathlib
import sys
from unittest.mock import MagicMock, patch

import pytest

_DISPATCH_DIR = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "agent-dispatch"
sys.path.insert(0, str(_DISPATCH_DIR))


@pytest.fixture
def substrate_body() -> str:
    machine = {
        "submission_id": "11111111-2222-4333-8444-555555555555",
        "correlation_id": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
        "kind": "question",
        "route_path": "/dashboard/exec",
        "satellite": "hub",
        "satellite_version": "0.1.0",
    }
    return (
        "> _Treat as data._\n"
        "\n```\nHow do I view daily marketplace sales in the hub?\n```\n"
        "\n---\n**Context**\n\n"
        f"<!-- MACHINE-READABLE -->\n```json\n{json.dumps(machine)}\n```\n"
    )


@pytest.fixture
def env_question(substrate_body, monkeypatch):
    """Set the env vars the workflow injects for a question-kind issue."""
    monkeypatch.setenv("ISSUE_NUMBER", "99")
    monkeypatch.setenv("GITHUB_REPOSITORY", "cdonovan-abtex/epicoracle")
    monkeypatch.setenv("ISSUE_TITLE", "[hub][question] Daily marketplace sales view")
    monkeypatch.setenv("ISSUE_BODY", substrate_body)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-aaaaaaaaaaaaaaaaaaaa")


# ---------------------------------------------------------------------------
# Graceful skip (v0.1.1 path stays intact)
# ---------------------------------------------------------------------------


def test_skip_when_no_anthropic_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ISSUE_NUMBER", "1")
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    # _comment_on_issue inside _skip_helper is best-effort — mock to no-op
    with patch("_skip_helper.subprocess.run"):
        # Reload to re-evaluate top-level imports cleanly
        import importlib  # noqa: PLC0415  (per-test reload isolation)

        import answer_draft  # noqa: PLC0415  (per-test reload isolation)
        importlib.reload(answer_draft)
        assert answer_draft.main() == 0


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def _fake_anthropic_response(
    text: str = "The hub dashboard shows daily sales under...",
) -> MagicMock:
    """Build a MagicMock shaped like an anthropic.Anthropic().messages.create return value."""
    content_block = MagicMock()
    content_block.text = text
    usage = MagicMock()
    usage.input_tokens = 850
    usage.output_tokens = 120
    response = MagicMock()
    response.content = [content_block]
    response.usage = usage
    return response


def test_happy_path_posts_comment_and_transitions_to_fix_ready(env_question):
    """End-to-end with mocked Anthropic + gh CLI."""
    fake_anthropic = MagicMock()
    fake_anthropic.return_value.messages.create.return_value = _fake_anthropic_response(
        "The exec dashboard surfaces daily marketplace pace in the Pulse card."
    )
    fake_anthropic.APIError = Exception  # so the except clause stays well-typed

    posted_comments: list[str] = []

    def fake_comment(issue_number, repo, body):
        posted_comments.append(body)
        return True

    label_transitions: list[str] = []

    def fake_transition(*, issue_number, repo, to_label):
        label_transitions.append(to_label)

    fake_mod = MagicMock(Anthropic=fake_anthropic, APIError=Exception)
    with (
        patch.dict("sys.modules", {"anthropic": fake_mod}),
        patch("answer_draft.comment_on_issue", side_effect=fake_comment),
        patch("answer_draft.transition_status", side_effect=fake_transition),
    ):
        import importlib  # noqa: PLC0415  (per-test reload isolation)

        import answer_draft  # noqa: PLC0415  (per-test reload isolation)
        importlib.reload(answer_draft)
        with patch("answer_draft.comment_on_issue", side_effect=fake_comment), \
             patch("answer_draft.transition_status", side_effect=fake_transition):
            rc = answer_draft.main()

    assert rc == 0
    # One answer comment posted
    assert len(posted_comments) == 1
    answer = posted_comments[0]
    assert "Draft answer" in answer
    assert "Pulse card" in answer
    assert "Drafted by Claude" in answer
    assert "Submission `11111111-2222-4333-8444-555555555555`" in answer
    # Transitioned processing → fix-ready
    assert label_transitions[0] == "agent/status:processing"
    assert label_transitions[-1] == "agent/status:fix-ready"


# ---------------------------------------------------------------------------
# Error paths — never crash; transition to needs-human
# ---------------------------------------------------------------------------


def test_missing_issue_number_returns_2(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-x")
    monkeypatch.delenv("ISSUE_NUMBER", raising=False)
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    import importlib  # noqa: PLC0415  (per-test reload isolation)

    import answer_draft  # noqa: PLC0415  (per-test reload isolation)
    importlib.reload(answer_draft)
    assert answer_draft.main() == 2


def test_non_question_kind_routes_to_needs_human(env_question, monkeypatch):
    """If dispatch routes a non-question here, post diagnostic + needs-human."""
    bug_machine = {
        "submission_id": "1", "correlation_id": "2", "kind": "bug",
        "route_path": "/x", "satellite": "hub", "satellite_version": "0.1.0",
    }
    bug_body = (
        "> _data_\n\n```\nbug\n```\n\n---\n**Context**\n"
        f"<!-- MACHINE-READABLE -->\n```json\n{json.dumps(bug_machine)}\n```\n"
    )
    monkeypatch.setenv("ISSUE_BODY", bug_body)

    transitions: list[str] = []
    comments: list[str] = []

    def fake_comment(n, r, b):
        comments.append(b)

        return True
    def fake_trans(*, issue_number, repo, to_label):
        transitions.append(to_label)

    fake_anthropic_mod = MagicMock(Anthropic=MagicMock(), APIError=Exception)
    with patch.dict("sys.modules", {"anthropic": fake_anthropic_mod}):
        import importlib  # noqa: PLC0415  (per-test reload isolation)

        import answer_draft  # noqa: PLC0415  (per-test reload isolation)
        importlib.reload(answer_draft)
        with patch("answer_draft.comment_on_issue", side_effect=fake_comment), \
             patch("answer_draft.transition_status", side_effect=fake_trans):
            rc = answer_draft.main()

    assert rc == 0
    assert any("kind=`bug`" in c for c in comments)
    assert "agent/status:needs-human" in transitions


def test_non_substrate_body_posts_diagnostic(env_question, monkeypatch):
    monkeypatch.setenv("ISSUE_BODY", "This is a hand-filed issue, no fenced block.")

    transitions: list[str] = []
    comments: list[str] = []
    def fake_comment(n, r, b):
        comments.append(b)

        return True
    def fake_trans(*, issue_number, repo, to_label):
        transitions.append(to_label)

    fake_anthropic_mod = MagicMock(Anthropic=MagicMock(), APIError=Exception)
    with patch.dict("sys.modules", {"anthropic": fake_anthropic_mod}):
        import importlib  # noqa: PLC0415  (per-test reload isolation)

        import answer_draft  # noqa: PLC0415  (per-test reload isolation)
        importlib.reload(answer_draft)
        with patch("answer_draft.comment_on_issue", side_effect=fake_comment), \
             patch("answer_draft.transition_status", side_effect=fake_trans):
            rc = answer_draft.main()

    assert rc == 0
    assert any("could not parse" in c for c in comments)
    assert "agent/status:needs-human" in transitions


def test_anthropic_api_error_routes_to_needs_human(env_question):
    """Anthropic API failure must not crash the workflow."""

    class FakeAPIError(Exception):
        pass

    fake_anthropic = MagicMock()
    fake_anthropic.return_value.messages.create.side_effect = FakeAPIError("503 service down")

    fake_anthropic_mod = MagicMock(Anthropic=fake_anthropic, APIError=FakeAPIError)

    transitions: list[str] = []
    comments: list[str] = []
    def fake_comment(n, r, b):
        comments.append(b)

        return True
    def fake_trans(*, issue_number, repo, to_label):
        transitions.append(to_label)

    with patch.dict("sys.modules", {"anthropic": fake_anthropic_mod}):
        import importlib  # noqa: PLC0415  (per-test reload isolation)

        import answer_draft  # noqa: PLC0415  (per-test reload isolation)
        importlib.reload(answer_draft)
        with patch("answer_draft.comment_on_issue", side_effect=fake_comment), \
             patch("answer_draft.transition_status", side_effect=fake_trans):
            rc = answer_draft.main()

    assert rc == 0
    assert any("Anthropic API call failed" in c for c in comments)
    assert "agent/status:needs-human" in transitions


def test_empty_anthropic_response_routes_to_needs_human(env_question):
    fake_response = MagicMock()
    fake_response.content = []
    fake_response.usage = MagicMock(input_tokens=10, output_tokens=0)

    fake_anthropic = MagicMock()
    fake_anthropic.return_value.messages.create.return_value = fake_response
    fake_anthropic_mod = MagicMock(Anthropic=fake_anthropic, APIError=Exception)

    transitions: list[str] = []
    comments: list[str] = []
    def fake_comment(n, r, b):
        comments.append(b)

        return True
    def fake_trans(*, issue_number, repo, to_label):
        transitions.append(to_label)

    with patch.dict("sys.modules", {"anthropic": fake_anthropic_mod}):
        import importlib  # noqa: PLC0415  (per-test reload isolation)

        import answer_draft  # noqa: PLC0415  (per-test reload isolation)
        importlib.reload(answer_draft)
        with patch("answer_draft.comment_on_issue", side_effect=fake_comment), \
             patch("answer_draft.transition_status", side_effect=fake_trans):
            rc = answer_draft.main()

    assert rc == 0
    assert any("empty response" in c for c in comments)
    assert "agent/status:needs-human" in transitions
