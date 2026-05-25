"""Tests for scripts/agent-dispatch/trinity_dispatch.py.

Mocks the OpenAI + Google + Anthropic clients so tests are fast,
deterministic, and don't touch real APIs.

Coverage:
  - graceful skip when CODEX_API_KEY or ANTHROPIC_API_KEY unset
  - non-suggestion kind bails to human
  - reconciliation rendering: convergent + divergent + next-steps sections
  - half-trinity fallback: Gemini failure produces synthetic sidecar so
    reconciler still runs
  - full failure paths (Codex fails entirely, reconciler fails)
"""

from __future__ import annotations

import json
import pathlib
import sys
from unittest.mock import patch

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
    monkeypatch.setenv("GEMINI_API_KEY", "g-test")
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


def _gemini_critique() -> dict:
    return {
        "reviewer": "gemini",
        "recommendation": "iterate",
        "summary": "Operator value depends on what KPIs land.",
        "pros": ["Operator-asked-for", "Hub becomes ops dashboard"],
        "cons": ["Designing the KPI cards is the hard part"],
        "implementation_sketch": "Start with just health pings; add metrics later.",
        "risks": ["Scope creep into a full BI tool"],
        "open_questions": ["Which metrics matter most to Vanessa?"],
        "confidence": "medium",
    }


def _reconciliation() -> dict:
    return {
        "convergent_points": [
            "Both agree the underlying capability is doable",
            "Both flagged design tension around KPI selection",
        ],
        "divergent_points": [
            {
                "topic": "Initial scope",
                "codex_view": "Ship the polling layer first",
                "gemini_view": "Don't ship without KPI clarity",
            }
        ],
        "unified_recommendation": "iterate",
        "rationale": "The plumbing is straightforward; the product question is open.",
        "next_steps": [
            "Christian + Vanessa pick 3 KPIs",
            "Spike the polling endpoint",
        ],
        "open_questions_for_christian": [
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
        gemini_recommendation="iterate",
        codex_model="codex-test",
        gemini_model="gemini-test",
        reconciler_model="claude-test",
        submission_id="abc-123",
    )
    assert "Unified recommendation" in rendered
    assert "iterate" in rendered
    assert "Both critiques converged on" in rendered
    assert "Where the critiques diverged" in rendered
    assert "Initial scope" in rendered
    assert "Next steps" in rendered
    assert "[ ] Christian + Vanessa pick 3 KPIs" in rendered
    assert "Open questions for Christian" in rendered
    assert "Which 3 KPIs" in rendered
    assert "Submission `abc-123`" in rendered


def test_render_handles_empty_divergent_section():
    rec = _reconciliation()
    rec["divergent_points"] = []
    rendered = trinity_dispatch._render_reconciliation_comment(
        rec,
        codex_recommendation="build",
        gemini_recommendation="build",
        codex_model="c", gemini_model="g", reconciler_model="r",
        submission_id="x",
    )
    assert "Where the critiques diverged" not in rendered


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
            codex_recommendation="x", gemini_recommendation="x",
            codex_model="c", gemini_model="g", reconciler_model="r",
            submission_id="x",
        )
        assert emoji in rendered


# ---------------------------------------------------------------------------
# Half-trinity fallback (Gemini failure / unavailable)
# ---------------------------------------------------------------------------


def test_half_trinity_when_gemini_unavailable(suggestion_env, monkeypatch):
    """If GEMINI_API_KEY isn't set, Codex runs alone + reconciler still fires
    with a synthetic Gemini sidecar noting half-trinity."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    posted: list[str] = []
    transitions: list[str] = []

    import importlib  # noqa: PLC0415
    importlib.reload(trinity_dispatch)
    with (
        patch("trinity_dispatch._run_codex", return_value=_codex_critique()),
        patch("trinity_dispatch._run_gemini", return_value=None) as gemini_mock,
        patch("trinity_dispatch._run_reconciler", return_value=_reconciliation()),
        patch(
            "trinity_dispatch.comment_on_issue",
            side_effect=lambda n, r, b: posted.append(b) or True,
        ),
        patch(
            "trinity_dispatch.transition_status",
            side_effect=lambda **kw: transitions.append(kw["to_label"]),
        ),
    ):
        rc = trinity_dispatch.main()

    assert rc == 0
    # Gemini not called when key absent
    gemini_mock.assert_not_called()
    # Reconciliation comment posted
    assert len(posted) >= 1
    assert "Trinity analysis" in posted[0]
    assert "agent/status:fix-ready" in transitions


# ---------------------------------------------------------------------------
# Codex failure path
# ---------------------------------------------------------------------------


def test_codex_failure_bails_to_human(suggestion_env):
    posted: list[str] = []
    transitions: list[str] = []

    import importlib  # noqa: PLC0415
    importlib.reload(trinity_dispatch)
    with (
        patch("trinity_dispatch._run_codex", return_value=None),
        patch("trinity_dispatch._run_gemini", return_value=_gemini_critique()),
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
    assert "agent/status:needs-human" in transitions


def test_reconciler_failure_bails_to_human(suggestion_env):
    posted: list[str] = []
    transitions: list[str] = []

    import importlib  # noqa: PLC0415
    importlib.reload(trinity_dispatch)
    with (
        patch("trinity_dispatch._run_codex", return_value=_codex_critique()),
        patch("trinity_dispatch._run_gemini", return_value=_gemini_critique()),
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
# Happy path (full trinity)
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
        patch("trinity_dispatch._run_gemini", return_value=_gemini_critique()),
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
    assert "Trinity analysis" in body
    assert "Unified recommendation" in body
    assert "iterate" in body  # from _reconciliation()
    assert "Codex" in body
    assert "Gemini" in body
    assert "agent/status:processing" in transitions
    assert "agent/status:fix-ready" in transitions
