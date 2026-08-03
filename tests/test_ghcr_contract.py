from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

from epicoracle_feedback.ghcr import resolve_ghcr_image, sandbox_pull_enabled


def _load_sandbox_repro() -> Any:
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "scripts" / "agent-dispatch" / "sandbox_repro.py"
    spec = importlib.util.spec_from_file_location("sandbox_repro_contract", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["sandbox_repro_contract"] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("flag", "expected"),
    [
        (None, False),
        ("", False),
        ("false", False),
        ("0", False),
        ("true", True),
        ("YES", True),
    ],
)
def test_sandbox_pull_enabled_flag(flag: str | None, expected: bool) -> None:
    assert sandbox_pull_enabled(flag) is expected


def test_default_disabled_sandbox_skips_pull_and_container(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_sandbox_repro()
    called = False

    def boom(*_: Any, **__: Any) -> bool:
        nonlocal called
        called = True
        raise AssertionError("GHCR helpers must not run while disabled")

    monkeypatch.delenv("GHCR_SANDBOX_ENABLED", raising=False)
    monkeypatch.setattr(module, "_pull_image", boom)
    monkeypatch.setattr(module, "_start_container", boom)

    assert module.main() == 0
    assert called is False


def test_explicit_identity_validation_and_hub_separation() -> None:
    assert resolve_ghcr_image("abtex/epicoracle") == "ghcr.io/abtex/epicoracle:main-latest"
    assert "cdonovan-abtex" not in resolve_ghcr_image("abtex/epicoracle")
    assert resolve_ghcr_image(
        "abtex/epicoracle",
        package_name="epicoracle-hub",
    ) == "ghcr.io/abtex/epicoracle-hub:main-latest"


@pytest.mark.parametrize("package_name", ["", " ", "bad name", "bad/name", "-bad", "bad-"])
def test_malformed_package_identity_refused(package_name: str) -> None:
    with pytest.raises(ValueError):
        resolve_ghcr_image("abtex/epicoracle", package_name=package_name)


@pytest.mark.parametrize("repository", ["", "abtex", "abtex/one/two"])
def test_malformed_repository_refused(repository: str) -> None:
    with pytest.raises(ValueError):
        resolve_ghcr_image(repository)


def test_empty_explicit_package_name_refused_when_opted_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_sandbox_repro()
    monkeypatch.setenv("GHCR_SANDBOX_ENABLED", "true")
    monkeypatch.setenv("GITHUB_REPOSITORY", "abtex/epicoracle")
    monkeypatch.setenv("ISSUE_NUMBER", "1")
    monkeypatch.setenv("ISSUE_BODY", "Route: `/tracking`")
    monkeypatch.setenv("CODEX_API_KEY", "sk-test")
    monkeypatch.setenv("GHCR_PACKAGE_NAME", "")

    assert module.main() == 2
