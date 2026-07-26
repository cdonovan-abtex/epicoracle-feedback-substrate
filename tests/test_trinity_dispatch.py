"""Tests for scripts/agent-dispatch/trinity_dispatch.py.

As of v0.2.2 the script implements a 2-voice review: Codex structured
critique (via the OpenAI Responses API) + Claude reconciliation. The
file is still named ``trinity_dispatch.py`` because the triage
classifier routes by the ``"trinity"`` key and renaming would force
consuming workflows to update.

Mocks the OpenAI + Anthropic clients so tests are fast, deterministic,
and don't touch real APIs.

Coverage:
  - graceful skip when CODEX_API_KEY or ANTHROPIC_API_KEY unset
  - non-suggestion kind bails to human
  - reconciliation rendering: convergent + divergent + next-steps sections
  - failure paths (Codex fails, reconciler fails)
  - happy path
  - _run_codex uses the Responses API shape (text_format=, input=,
    max_output_tokens=, output_parsed)
"""

from __future__ import annotations

import json
import pathlib
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

_DISPATCH_DIR = (
    pathlib.Path(__file__).resolve().parent.parent
    / "scripts"
    / "agent-dispatch"
)
sys.path.insert(0, str(_DISPATCH_DIR))

import trinity_dispatch  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def suggestion_env(monkeypatch):
    machine = {
        "submission_id": "aaaaaaaa-1111-4222-8333-444444444444",
        "correlation_id": "bbbbbbbb-2222-4333-8444-555555555555",
        "kind": "suggestion",
        "route_path": "/dashboard/exec",
        "satellite": "hub",
        "satellite_version": "0.1.0",
    }
    body = (
        "> _data_\n"
        "\n```\nIt would be useful to have a Satellites tab on the hub showing "
        "live health for marketplace + compliance.\n```\n"
        "\n---\n**Context**\n\n"
        f"<!-- MACHINE-READABLE -->\n```json\n{json.dumps(machine)}\n```\n"
    )
    monkeypatch.setenv("CODEX_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("ISSUE_NUMBER", "21")
    monkeypatch.setenv("GITHUB_REPOSITORY", "cdonovan-abtex/epicoracle")
    monkeypatch.setenv("ISSUE_TITLE", "[hub][suggestion] Satellites tab")
    monkeypatch.setenv("ISSUE_BODY", body)


def _codex_critique() -> dict:
    return {
        "reviewer": "codex",
        "recommendation": "iterate",
        "summary": "Doable. Single Next.js route + polling backend endpoints.",
        "pros": ["Modular", "Reuses existing /api/health"],
        "cons": ["Hub becomes coupled to satellite uptime"],
        "implementation_sketch": "Add /satellites route + cards.",
        "risks": ["Stale data display", "CORS"],
        "open_questions": ["Polling cadence?"],
        "confidence": "medium",
    }


def _reconciliation() -> dict:
    return {
        "convergent_points": [
            "Codex's implementation sketch matches the operator's ask",
            "Both noted KPI selection is the harder design problem",
        ],
        "divergent_points": [
            {
                "topic": "Initial scope",
                "codex_view": "Ship the polling layer first",
                "claude_view": "Don't ship without KPI clarity",
            }
        ],
        "unified_recommendation": "iterate",
        "rationale": "The plumbing is straightforward; the product question is open.",
        "next_steps": [
            "Product owner + marketplace operator pick 3 KPIs",
            "Spike the polling endpoint",
        ],
        trinity_dispatch.OWNER_QUESTIONS_KEY: [
            "Which 3 KPIs unlock first value?",
            "Polling cadence target?",
        ],
        "confidence": "medium",
    }


# ---------------------------------------------------------------------------
# Skip + env validation
# ---------------------------------------------------------------------------


def test_skip_when_no_codex_key(monkeypatch):
    monkeypatch.delenv("CODEX_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    monkeypatch.setenv("ISSUE_NUMBER", "1")
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    with patch("_skip_helper.subprocess.run"):
        import importlib  # noqa: PLC0415
        importlib.reload(trinity_dispatch)
        assert trinity_dispatch.main() == 0


def test_skip_when_no_anthropic_key(monkeypatch):
    monkeypatch.setenv("CODEX_API_KEY", "sk")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ISSUE_NUMBER", "1")
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    with patch("_skip_helper.subprocess.run"):
        import importlib  # noqa: PLC0415
        importlib.reload(trinity_dispatch)
        assert trinity_dispatch.main() == 0


# ---------------------------------------------------------------------------
# Non-suggestion → bails
# ---------------------------------------------------------------------------


def test_non_suggestion_kind_bails(monkeypatch):
    machine = {
        "submission_id": "x", "correlation_id": "y", "kind": "bug",
        "route_path": "/x", "satellite": "hub", "satellite_version": "0.1.0",
    }
    body = (
        "> _data_\n```\nb\n```\n\n---\n**Context**\n\n"
        f"<!-- MACHINE-READABLE -->\n```json\n{json.dumps(machine)}\n```\n"
    )
    monkeypatch.setenv("CODEX_API_KEY", "sk")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    monkeypatch.setenv("ISSUE_NUMBER", "1")
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("ISSUE_TITLE", "b")
    monkeypatch.setenv("ISSUE_BODY", body)

    posted: list[str] = []
    transitions: list[str] = []
    import importlib  # noqa: PLC0415
    importlib.reload(trinity_dispatch)
    with (
        patch("trinity_dispatch.comment_on_issue",
              side_effect=lambda n, r, b: posted.append(b) or True),
        patch("trinity_dispatch.transition_status",
              side_effect=lambda **kw: transitions.append(kw["to_label"])),
    ):
        assert trinity_dispatch.main() == 0
    assert any("kind=`bug`" in c for c in posted)
    assert "agent/status:needs-human" in transitions


# ---------------------------------------------------------------------------
# Reconciliation rendering
# ---------------------------------------------------------------------------


def test_render_includes_convergent_divergent_next_steps_questions():
    rendered = trinity_dispatch._render_reconciliation_comment(
        _reconciliation(),
        codex_recommendation="iterate",
        codex_model="codex-test",
        reconciler_model="claude-test",
        submission_id="abc-123",
    )
    assert "Review analysis" in rendered
    assert "Unified recommendation" in rendered
    assert "iterate" in rendered
    assert "converged" in rendered
    assert "diverged" in rendered
    assert "Initial scope" in rendered
    assert "Next steps" in rendered
    assert "[ ] Product owner + marketplace operator pick 3 KPIs" in rendered
    assert "Open questions for product owner" in rendered
    assert "Which 3 KPIs" in rendered
    assert "Submission `abc-123`" in rendered
    # Two-voice attribution — Codex + Claude, no Gemini.
    assert "Codex" in rendered
    assert "Claude" in rendered
    assert "Gemini" not in rendered


def test_reconciler_role_key_is_shared_by_prompt_and_renderer():
    assert trinity_dispatch.OWNER_QUESTIONS_KEY in trinity_dispatch.RECONCILER_SYSTEM_PROMPT


def test_render_handles_empty_divergent_section():
    rec = _reconciliation()
    rec["divergent_points"] = []
    rendered = trinity_dispatch._render_reconciliation_comment(
        rec,
        codex_recommendation="build",
        codex_model="c", reconciler_model="r",
        submission_id="x",
    )
    assert "diverged" not in rendered


def test_render_recommendation_emojis():
    for rec_value, emoji in (
        ("build", "🟢"),
        ("iterate", "🟡"),
        ("decline", "🔴"),
        ("needs-discussion", "💬"),
    ):
        rec = _reconciliation()
        rec["unified_recommendation"] = rec_value
        rendered = trinity_dispatch._render_reconciliation_comment(
            rec,
            codex_recommendation="x",
            codex_model="c", reconciler_model="r",
            submission_id="x",
        )
        assert emoji in rendered


# ---------------------------------------------------------------------------
# _run_codex — Responses API shape verification
# ---------------------------------------------------------------------------


def test_run_codex_uses_responses_api_shape():
    """Pin the Responses API call shape: input=, text_format=,
    max_output_tokens=, and parsed via response.output_parsed. This is the
    contract gpt-5-codex requires; chat.completions.parse 404s for that
    model."""
    fake_parsed_obj = MagicMock()
    fake_parsed_obj.model_dump.return_value = _codex_critique()
    fake_response = SimpleNamespace(output_parsed=fake_parsed_obj)

    fake_client = MagicMock()
    fake_client.responses.parse.return_value = fake_response

    fake_openai_module = MagicMock()
    fake_openai_module.OpenAI.return_value = fake_client
    fake_openai_module.OpenAIError = Exception

    with patch.dict(sys.modules, {"openai": fake_openai_module}):
        out = trinity_dispatch._run_codex(
            user_message="hello",
            model="gpt-5-codex",
            api_key="sk-test",
        )

    assert out == _codex_critique()
    # Verify the call shape — these kwargs are the fix for the 404.
    assert fake_client.responses.parse.called
    call_kwargs = fake_client.responses.parse.call_args.kwargs
    assert call_kwargs["model"] == "gpt-5-codex"
    assert "input" in call_kwargs and isinstance(call_kwargs["input"], list)
    assert call_kwargs["input"][0]["role"] == "system"
    assert call_kwargs["input"][1]["role"] == "user"
    assert "text_format" in call_kwargs  # NOT response_format
    assert "max_output_tokens" in call_kwargs  # NOT max_completion_tokens
    assert "response_format" not in call_kwargs
    assert "max_completion_tokens" not in call_kwargs
    assert "messages" not in call_kwargs


def test_run_codex_returns_none_when_output_parsed_is_none():
    fake_response = SimpleNamespace(output_parsed=None)
    fake_client = MagicMock()
    fake_client.responses.parse.return_value = fake_response

    fake_openai_module = MagicMock()
    fake_openai_module.OpenAI.return_value = fake_client
    fake_openai_module.OpenAIError = Exception

    with patch.dict(sys.modules, {"openai": fake_openai_module}):
        out = trinity_dispatch._run_codex(
            user_message="hi", model="gpt-5-codex", api_key="sk",
        )
    assert out is None


# ---------------------------------------------------------------------------
# Codex / reconciler failure paths
# ---------------------------------------------------------------------------


def test_codex_failure_bails_to_human(suggestion_env):
    posted: list[str] = []
    transitions: list[str] = []

    import importlib  # noqa: PLC0415
    importlib.reload(trinity_dispatch)
    with (
        patch("trinity_dispatch._run_codex", return_value=None),
        patch("trinity_dispatch._run_reconciler") as recon_mock,
        patch("trinity_dispatch.comment_on_issue",
              side_effect=lambda n, r, b: posted.append(b) or True),
        patch("trinity_dispatch.transition_status",
              side_effect=lambda **kw: transitions.append(kw["to_label"])),
    ):
        rc = trinity_dispatch.main()

    assert rc == 0
    recon_mock.assert_not_called()  # don't reconcile if Codex failed
    assert any("Codex side failed" in c for c in posted)
    # Bail message now uses "review-dispatch" framing, not "trinity".
    assert any("review-dispatch" in c for c in posted)
    assert "agent/status:needs-human" in transitions


def test_reconciler_failure_bails_to_human(suggestion_env):
    posted: list[str] = []
    transitions: list[str] = []

    import importlib  # noqa: PLC0415
    importlib.reload(trinity_dispatch)
    with (
        patch("trinity_dispatch._run_codex", return_value=_codex_critique()),
        patch("trinity_dispatch._run_reconciler", return_value=None),
        patch("trinity_dispatch.comment_on_issue",
              side_effect=lambda n, r, b: posted.append(b) or True),
        patch("trinity_dispatch.transition_status",
              side_effect=lambda **kw: transitions.append(kw["to_label"])),
    ):
        rc = trinity_dispatch.main()

    assert rc == 0
    assert any("reconciler (Claude) failed" in c for c in posted)
    assert "agent/status:needs-human" in transitions


# ---------------------------------------------------------------------------
# Happy path (2-voice review)
# ---------------------------------------------------------------------------


def test_happy_path_posts_reconciliation_and_transitions_to_fix_ready(
    suggestion_env,
):
    posted: list[str] = []
    transitions: list[str] = []

    import importlib  # noqa: PLC0415
    importlib.reload(trinity_dispatch)
    with (
        patch("trinity_dispatch._run_codex", return_value=_codex_critique()),
        patch("trinity_dispatch._run_reconciler", return_value=_reconciliation()),
        patch("trinity_dispatch.comment_on_issue",
              side_effect=lambda n, r, b: posted.append(b) or True),
        patch("trinity_dispatch.transition_status",
              side_effect=lambda **kw: transitions.append(kw["to_label"])),
    ):
        rc = trinity_dispatch.main()

    assert rc == 0
    assert len(posted) == 1
    body = posted[0]
    assert "Review analysis" in body
    assert "Unified recommendation" in body
    assert "iterate" in body  # from _reconciliation()
    assert "Codex" in body
    assert "Claude" in body
    assert "Gemini" not in body
    assert "agent/status:processing" in transitions
    assert "agent/status:fix-ready" in transitions


# ---------------------------------------------------------------------------
# Reconciler message no longer references Gemini
# ---------------------------------------------------------------------------


def test_reconciler_message_omits_gemini():
    """The reconciler message contains operator content + Codex's critique
    only. No Gemini section."""
    body = (
        "> _data_\n```\nsomething\n```\n\n---\n**Context**\n\n"
        "<!-- MACHINE-READABLE -->\n```json\n"
        + json.dumps({
            "submission_id": "s", "correlation_id": "c", "kind": "suggestion",
            "route_path": "/x", "satellite": "hub", "satellite_version": "0.1.0",
        }) + "\n```\n"
    )
    parsed = trinity_dispatch.parse_issue_body(body)
    msg = trinity_dispatch._build_reconciler_message(
        issue_title="[hub][suggestion] Foo",
        parsed=parsed,
        codex_critique=_codex_critique(),
    )
    assert "Codex critique" in msg
    assert "Gemini" not in msg
