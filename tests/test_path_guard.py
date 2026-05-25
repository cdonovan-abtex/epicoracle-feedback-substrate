"""Path-allowlist guard tests.

The PR-time path-guard runs as a step in the agent-dispatch workflow. It
fails the workflow if the agent's PR touches paths the v2 brief marks
off-limits to agents:

* ``.github/workflows/**`` — workflow drift = privilege escalation
* ``Dockerfile`` — image trust boundary
* ``deploy/**`` — deploy automation
* ``auth/**`` — auth/identity code
* secret config files (``.env*``, anything matching key/secret patterns)

The script is small and pure: given a list of changed file paths, return
the subset that violates policy. Tests cover positive (allowed paths) and
negative (blocked paths) cases.

We import the script as a module to test its function directly rather
than shelling out — the script's ``__main__`` path is tested end-to-end
by the workflow itself.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest


def _load_path_guard() -> Any:
    """Load scripts/agent-dispatch/path_guard.py as a module."""
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "scripts" / "agent-dispatch" / "path_guard.py"
    spec = importlib.util.spec_from_file_location("path_guard", script)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["path_guard"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def path_guard() -> Any:
    return _load_path_guard()


def test_allowed_paths_no_violations(path_guard: Any) -> None:
    paths = [
        "src/foo/bar.py",
        "tests/test_foo.py",
        "frontend/src/components/Foo.tsx",
        "README.md",
        "CHANGELOG.md",
        "pyproject.toml",
    ]
    assert path_guard.find_blocked_paths(paths) == []


def test_workflow_file_blocked(path_guard: Any) -> None:
    paths = [".github/workflows/agent-dispatch.yml"]
    violations = path_guard.find_blocked_paths(paths)
    assert violations == [".github/workflows/agent-dispatch.yml"]


def test_workflow_nested_file_blocked(path_guard: Any) -> None:
    paths = [".github/workflows/sub/build.yml"]
    assert ".github/workflows/sub/build.yml" in path_guard.find_blocked_paths(paths)


def test_dockerfile_blocked(path_guard: Any) -> None:
    assert "Dockerfile" in path_guard.find_blocked_paths(["Dockerfile"])
    assert "backend/Dockerfile" in path_guard.find_blocked_paths(["backend/Dockerfile"])


def test_deploy_dir_blocked(path_guard: Any) -> None:
    assert "deploy/k8s/app.yaml" in path_guard.find_blocked_paths(["deploy/k8s/app.yaml"])


def test_auth_dir_blocked(path_guard: Any) -> None:
    assert "auth/middleware.py" in path_guard.find_blocked_paths(["auth/middleware.py"])
    assert "backend/auth/jwt.py" in path_guard.find_blocked_paths(["backend/auth/jwt.py"])


def test_env_files_blocked(path_guard: Any) -> None:
    assert ".env" in path_guard.find_blocked_paths([".env"])
    assert ".env.production" in path_guard.find_blocked_paths([".env.production"])


def test_secret_config_files_blocked(path_guard: Any) -> None:
    assert "config/secrets.yaml" in path_guard.find_blocked_paths(["config/secrets.yaml"])
    assert "keys/private.pem" in path_guard.find_blocked_paths(["keys/private.pem"])


def test_mixed_allowed_and_blocked(path_guard: Any) -> None:
    paths = [
        "src/foo.py",
        ".github/workflows/test.yml",
        "tests/test_foo.py",
        "Dockerfile",
    ]
    violations = path_guard.find_blocked_paths(paths)
    assert ".github/workflows/test.yml" in violations
    assert "Dockerfile" in violations
    assert "src/foo.py" not in violations
    assert "tests/test_foo.py" not in violations


def test_empty_list_no_violations(path_guard: Any) -> None:
    assert path_guard.find_blocked_paths([]) == []
