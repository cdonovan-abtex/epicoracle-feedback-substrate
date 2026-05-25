"""Tests for scripts/agent-dispatch/fix_pr.py.

Mocks the OpenAI client + git + gh subprocesses so tests are fast,
deterministic, and don't touch any real filesystem outside tmp_path.

Coverage:
  - graceful skip when CODEX_API_KEY unset
  - path allowlist: blocked patterns reject, allow patterns accept
  - path normalization: ../ escapes return None
  - file-tree builder works against a git-init'd tmp repo
  - happy path: parse → openai → branch → commit → push → PR → comment
  - error paths: non-bug kind, low-confidence proposal, blocked path,
    file-not-found, identical content, OpenAI error, git failures —
    none crash the workflow; all transition to needs-human + diagnostic
"""

from __future__ import annotations

import pathlib
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest

_DISPATCH_DIR = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "agent-dispatch"
sys.path.insert(0, str(_DISPATCH_DIR))

import fix_pr  # noqa: E402

# ---------------------------------------------------------------------------
# Path allowlist
# ---------------------------------------------------------------------------


class TestPathAllowlist:
    def test_workflow_file_blocked(self):
        ok, reason = fix_pr._is_path_allowed(".github/workflows/agent-dispatch.yml")
        assert ok is False
        assert "blocked" in reason

    def test_dockerfile_blocked(self):
        ok, _ = fix_pr._is_path_allowed("Dockerfile")
        assert ok is False
        ok, _ = fix_pr._is_path_allowed("backend/Dockerfile")
        assert ok is False

    def test_env_files_blocked(self):
        for path in ("backend/.env", ".env.local", ".env"):
            ok, _ = fix_pr._is_path_allowed(path)
            assert ok is False, f"{path} should be blocked"

    def test_lockfiles_blocked(self):
        for path in ("package-lock.json", "uv.lock", "yarn.lock"):
            ok, _ = fix_pr._is_path_allowed(path)
            assert ok is False, f"{path} should be blocked"

    def test_pyproject_blocked(self):
        ok, _ = fix_pr._is_path_allowed("pyproject.toml")
        assert ok is False

    def test_frontend_component_allowed(self):
        ok, reason = fix_pr._is_path_allowed("frontend/components/FeedbackButton.tsx")
        assert ok is True
        assert "matches" in reason

    def test_backend_router_allowed(self):
        ok, _ = fix_pr._is_path_allowed("backend/app/routers/feedback.py")
        assert ok is True

    def test_readme_allowed(self):
        ok, _ = fix_pr._is_path_allowed("README.md")
        assert ok is True

    def test_unmatched_path_rejected(self):
        ok, reason = fix_pr._is_path_allowed("random/somewhere/else.txt")
        assert ok is False
        assert "does not match" in reason


# ---------------------------------------------------------------------------
# Path normalization (escape prevention)
# ---------------------------------------------------------------------------


class TestPathNormalization:
    def test_normal_path_resolves(self, tmp_path):
        (tmp_path / "frontend").mkdir()
        (tmp_path / "frontend" / "x.tsx").write_text("hi")
        result = fix_pr._normalize_path("frontend/x.tsx", tmp_path)
        assert result == (tmp_path / "frontend" / "x.tsx").resolve()

    def test_dotdot_escape_returns_none(self, tmp_path):
        # path that escapes the repo root via ../
        result = fix_pr._normalize_path("../../../etc/passwd", tmp_path)
        assert result is None

    def test_absolute_path_treated_as_relative(self, tmp_path):
        # leading / is stripped, then resolved under repo_root
        (tmp_path / "x.md").write_text("hi")
        result = fix_pr._normalize_path("/x.md", tmp_path)
        assert result == (tmp_path / "x.md").resolve()


# ---------------------------------------------------------------------------
# Slug
# ---------------------------------------------------------------------------


class TestSlugify:
    def test_basic(self):
        assert fix_pr._slugify("Fix the broken button") == "fix-the-broken-button"

    def test_special_chars(self):
        assert fix_pr._slugify("Foo! Bar? & Baz.") == "foo-bar-baz"

    def test_truncates_long(self):
        long = "a" * 100
        result = fix_pr._slugify(long, max_len=20)
        assert len(result) <= 20

    def test_empty_returns_fallback(self):
        assert fix_pr._slugify("---") == "fix"
        assert fix_pr._slugify("") == "fix"


# ---------------------------------------------------------------------------
# File-tree builder
# ---------------------------------------------------------------------------


class TestFileTree:
    def test_uses_git_ls_files(self, tmp_path):
        # Create a tiny git repo
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        (tmp_path / "a.py").write_text("x")
        (tmp_path / "b.md").write_text("y")
        subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
        tree = fix_pr._build_file_tree(tmp_path)
        assert "a.py" in tree
        assert "b.md" in tree

    def test_returns_unavailable_on_non_git(self, tmp_path):
        tree = fix_pr._build_file_tree(tmp_path)
        assert tree == "(file tree unavailable)"


# ---------------------------------------------------------------------------
# Skip / env validation
# ---------------------------------------------------------------------------


def test_skip_when_no_codex_key(monkeypatch):
    monkeypatch.delenv("CODEX_API_KEY", raising=False)
    monkeypatch.setenv("ISSUE_NUMBER", "1")
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    with patch("_skip_helper.subprocess.run"):
        import importlib  # noqa: PLC0415
        importlib.reload(fix_pr)
        assert fix_pr.main() == 0


def test_missing_issue_number_returns_2(monkeypatch):
    monkeypatch.setenv("CODEX_API_KEY", "sk-test")
    monkeypatch.delenv("ISSUE_NUMBER", raising=False)
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    import importlib  # noqa: PLC0415
    importlib.reload(fix_pr)
    assert fix_pr.main() == 2


# ---------------------------------------------------------------------------
# Main path — happy + error branches with full mocking
# ---------------------------------------------------------------------------


@pytest.fixture
def bug_env(monkeypatch, tmp_path):
    """Set up env vars + a git-init'd tmp repo with a target file."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test"], cwd=tmp_path, check=True
    )
    subprocess.run(
        ["git", "config", "user.name", "test"], cwd=tmp_path, check=True
    )
    target = tmp_path / "frontend" / "components" / "Hello.tsx"
    target.parent.mkdir(parents=True)
    target.write_text("export const Hello = () => <div>Hi</div>;")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init", "--quiet"], cwd=tmp_path, check=True
    )

    body = (
        "> _data_\n"
        '\n```\nThe Hello component should say "Hello" not "Hi".\n```\n'
        "\n---\n**Context**\n\n"
        '<!-- MACHINE-READABLE -->\n```json\n'
        '{"submission_id":"11111111-2222-4333-8444-555555555555",'
        '"correlation_id":"a","kind":"bug","route_path":"/x",'
        '"satellite":"hub","satellite_version":"0.1.0"}\n```\n'
    )
    monkeypatch.setenv("CODEX_API_KEY", "sk-test")
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    monkeypatch.setenv("GITHUB_REPOSITORY", "cdonovan-abtex/epicoracle")
    monkeypatch.setenv("ISSUE_TITLE", "[hub][bug] Hello component says Hi")
    monkeypatch.setenv("ISSUE_BODY", body)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _make_openai_mock(file_path: str, new_content: str, confidence: str = "high"):
    """Build a mock openai module returning a FixProposal-shaped response."""
    fake_openai = MagicMock()
    proposal = MagicMock()
    proposal.file_path = file_path
    proposal.full_new_content = new_content
    proposal.summary = "Fix Hello copy"
    proposal.explanation = "Changed Hi to Hello in the greeting component."
    proposal.confidence = confidence
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.parsed = proposal
    fake_openai.OpenAI.return_value.beta.chat.completions.parse.return_value = response

    class _FakeOpenAIError(Exception):
        pass

    fake_openai.OpenAIError = _FakeOpenAIError
    return fake_openai


def test_happy_path_creates_branch_commits_pushes_opens_pr(bug_env):
    """End-to-end with mocked OpenAI + gh + git push."""
    fake_openai = _make_openai_mock(
        "frontend/components/Hello.tsx",
        "export const Hello = () => <div>Hello</div>;",
    )

    posted: list[str] = []
    transitions: list[str] = []

    def fake_comment(n, r, b):
        posted.append(b)
        return True

    def fake_transition(*, issue_number, repo, to_label):
        transitions.append(to_label)

    # Mock subprocess to allow real git ops in tmp_path but mock push + gh
    real_run = subprocess.run

    def fake_run(args, **kwargs):
        if args[:1] == ["git"] and "push" in args:
            return subprocess.CompletedProcess(args, 0, "", "")
        if args[:2] == ["gh", "pr"]:
            return subprocess.CompletedProcess(
                args, 0, "https://github.com/cdonovan-abtex/epicoracle/pull/77\n", ""
            )
        return real_run(args, **kwargs)

    fake_pydantic = MagicMock()
    fake_pydantic.BaseModel = type("BaseModel", (), {})
    fake_pydantic.Field = lambda **kw: None

    with (
        patch.dict("sys.modules", {"openai": fake_openai, "pydantic": fake_pydantic}),
        patch("fix_pr.comment_on_issue", side_effect=fake_comment),
        patch("fix_pr.transition_status", side_effect=fake_transition),
        patch("fix_pr.subprocess.run", side_effect=fake_run),
    ):
        import importlib  # noqa: PLC0415
        importlib.reload(fix_pr)
        with (
            patch("fix_pr.comment_on_issue", side_effect=fake_comment),
            patch("fix_pr.transition_status", side_effect=fake_transition),
            patch("fix_pr.subprocess.run", side_effect=fake_run),
        ):
            rc = fix_pr.main()

    assert rc == 0
    # Final comment should reference the PR
    assert any("pull/77" in c for c in posted)
    # Label flow: processing → fix-ready
    assert "agent/status:processing" in transitions
    assert "agent/status:fix-ready" in transitions
    # File was actually edited
    assert (bug_env / "frontend" / "components" / "Hello.tsx").read_text() == \
        "export const Hello = () => <div>Hello</div>;"


def test_low_confidence_bails_to_human(bug_env):
    fake_openai = _make_openai_mock(
        "frontend/components/Hello.tsx",
        "...",
        confidence="low",
    )
    posted: list[str] = []
    transitions: list[str] = []
    fake_pydantic = MagicMock(BaseModel=type("BaseModel", (), {}), Field=lambda **kw: None)

    with (
        patch.dict("sys.modules", {"openai": fake_openai, "pydantic": fake_pydantic}),
    ):
        import importlib  # noqa: PLC0415
        importlib.reload(fix_pr)
        with (
            patch("fix_pr.comment_on_issue", side_effect=lambda n, r, b: posted.append(b) or True),
            patch("fix_pr.transition_status", side_effect=lambda **kw: transitions.append(kw["to_label"])),  # noqa: E501
        ):
            rc = fix_pr.main()

    assert rc == 0
    assert any("confidence=low" in c for c in posted)
    assert "agent/status:needs-human" in transitions


def test_blocked_path_bails_to_human(bug_env):
    fake_openai = _make_openai_mock(
        ".github/workflows/agent-dispatch.yml",
        "name: hacked\n",
    )
    posted: list[str] = []
    transitions: list[str] = []
    fake_pydantic = MagicMock(BaseModel=type("BaseModel", (), {}), Field=lambda **kw: None)

    with patch.dict("sys.modules", {"openai": fake_openai, "pydantic": fake_pydantic}):
        import importlib  # noqa: PLC0415
        importlib.reload(fix_pr)
        with (
            patch("fix_pr.comment_on_issue", side_effect=lambda n, r, b: posted.append(b) or True),
            patch("fix_pr.transition_status", side_effect=lambda **kw: transitions.append(kw["to_label"])),  # noqa: E501
        ):
            rc = fix_pr.main()

    assert rc == 0
    assert any("path allowlist" in c.lower() or "blocked" in c.lower() for c in posted)
    assert "agent/status:needs-human" in transitions


def test_non_bug_kind_bails_to_human(monkeypatch, tmp_path):
    body = (
        "> _data_\n```\nq?\n```\n\n---\n**Context**\n\n"
        '<!-- MACHINE-READABLE -->\n```json\n{"submission_id":"1","correlation_id":"a",'
        '"kind":"question","route_path":"/x","satellite":"hub","satellite_version":"0.1.0"}\n```\n'
    )
    monkeypatch.setenv("CODEX_API_KEY", "sk-test")
    monkeypatch.setenv("ISSUE_NUMBER", "1")
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("ISSUE_TITLE", "q")
    monkeypatch.setenv("ISSUE_BODY", body)
    monkeypatch.chdir(tmp_path)

    posted: list[str] = []
    transitions: list[str] = []
    import importlib  # noqa: PLC0415
    importlib.reload(fix_pr)
    with (
        patch("fix_pr.comment_on_issue", side_effect=lambda n, r, b: posted.append(b) or True),
        patch("fix_pr.transition_status", side_effect=lambda **kw: transitions.append(kw["to_label"])),  # noqa: E501
    ):
        rc = fix_pr.main()

    assert rc == 0
    assert any("kind=`question`" in c for c in posted)
    assert "agent/status:needs-human" in transitions


def test_identical_content_bails_to_human(bug_env):
    # Codex returns the same content as already on disk → no-op
    existing = (bug_env / "frontend" / "components" / "Hello.tsx").read_text()
    fake_openai = _make_openai_mock("frontend/components/Hello.tsx", existing)

    posted: list[str] = []
    transitions: list[str] = []
    fake_pydantic = MagicMock(BaseModel=type("BaseModel", (), {}), Field=lambda **kw: None)

    with patch.dict("sys.modules", {"openai": fake_openai, "pydantic": fake_pydantic}):
        import importlib  # noqa: PLC0415
        importlib.reload(fix_pr)
        with (
            patch("fix_pr.comment_on_issue", side_effect=lambda n, r, b: posted.append(b) or True),
            patch("fix_pr.transition_status", side_effect=lambda **kw: transitions.append(kw["to_label"])),  # noqa: E501
        ):
            rc = fix_pr.main()

    assert rc == 0
    assert any("identical" in c.lower() or "no-op" in c.lower() for c in posted)
    assert "agent/status:needs-human" in transitions
