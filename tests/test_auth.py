"""Auth resolution tests.

The dispatcher's token-resolution policy is simple but consequential:

1. Explicit kwarg wins.
2. ``GH_TOKEN`` env var second.
3. None → caller falls back to host gh auth (dev only).

The dispatcher's subprocess env-injection must never leak the token into
argv. ``test_dispatch::test_gh_token_kwarg_lands_in_subprocess_env_not_argv``
covers that end-to-end; this file covers the resolution primitives.
"""

from __future__ import annotations

import os

import pytest

from epicoracle_feedback import resolve_gh_token
from epicoracle_feedback.auth import gh_env


def test_explicit_kwarg_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GH_TOKEN", "from_env")
    assert resolve_gh_token("from_kwarg") == "from_kwarg"


def test_env_var_used_when_no_kwarg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GH_TOKEN", "from_env_only")
    assert resolve_gh_token() == "from_env_only"
    assert resolve_gh_token(None) == "from_env_only"


def test_empty_env_treated_as_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GH_TOKEN", "")
    assert resolve_gh_token() is None


def test_whitespace_env_treated_as_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GH_TOKEN", "   \n  ")
    assert resolve_gh_token() is None


def test_no_kwarg_no_env_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GH_TOKEN", raising=False)
    assert resolve_gh_token() is None


def test_gh_env_injects_token() -> None:
    env = gh_env("test_token_xyz")
    assert env["GH_TOKEN"] == "test_token_xyz"


def test_gh_env_passes_through_when_no_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GH_TOKEN", raising=False)
    env = gh_env(None)
    assert "GH_TOKEN" not in env


def test_gh_env_does_not_mutate_os_environ() -> None:
    """Sanity: building the subprocess env must not pollute our own."""
    before = os.environ.get("GH_TOKEN", "<absent>")
    gh_env("scratch_value")
    after = os.environ.get("GH_TOKEN", "<absent>")
    assert before == after
