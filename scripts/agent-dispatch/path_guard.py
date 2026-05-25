#!/usr/bin/env python3
"""Path-allowlist guard — fails the workflow if a PR touches blocked paths.

Run as a step in ``.github/workflows/agent-dispatch.yml``. Reads the list
of changed files via ``gh pr diff`` (or env-injected list for tests) and
exits non-zero if any path matches the block-list.

Block-list (per v2 brief):

* ``.github/workflows/**`` — workflow drift = privilege escalation
* ``Dockerfile`` (root or nested) — image trust boundary
* ``deploy/**`` — deploy automation
* ``auth/**`` (root or nested) — auth/identity code
* ``.env*`` — env file with secrets
* ``**/secrets/**``, ``**/secret*.{yaml,yml,json,toml}`` — secret config
* ``*.pem``, ``*.key`` — keys

This script is intentionally pure-function-first so it is unit-testable
without shelling out. See ``tests/test_path_guard.py``.
"""

from __future__ import annotations

import fnmatch
import os
import subprocess
import sys
from collections.abc import Iterable

# Block-list patterns. ``fnmatch`` style (glob, no regex).
BLOCKED_PATTERNS: tuple[str, ...] = (
    ".github/workflows/*",
    ".github/workflows/**/*",
    "Dockerfile",
    "*/Dockerfile",
    "**/Dockerfile",
    "deploy/*",
    "deploy/**/*",
    "auth/*",
    "auth/**/*",
    "*/auth/*",
    "**/auth/*",
    "**/auth/**/*",
    ".env",
    ".env.*",
    "**/secrets/**",
    "**/secret*.yaml",
    "**/secret*.yml",
    "**/secret*.json",
    "**/secret*.toml",
    "*.pem",
    "**/*.pem",
    "*.key",
    "**/*.key",
)


def _matches_any(path: str, patterns: Iterable[str]) -> bool:
    """Check ``path`` against the patterns using extended-glob semantics.

    ``fnmatch`` doesn't natively understand ``**`` so we expand both:
    ``fnmatch`` for single-level globs, and a manual prefix check for
    directory-recursive matches like ``deploy/**/*``.
    """
    for pattern in patterns:
        if fnmatch.fnmatchcase(path, pattern):
            return True
        # Handle '**' as multi-segment wildcard.
        if "**" in pattern:
            head, _, tail = pattern.partition("**")
            head = head.rstrip("/")
            tail = tail.lstrip("/")
            head_ok = not head or path.startswith(head + "/") or path == head
            tail_ok = (
                not tail or fnmatch.fnmatchcase(path, "*" + tail) or path.endswith(tail)
            )
            if head_ok and tail_ok:
                return True
    return False


def find_blocked_paths(paths: Iterable[str]) -> list[str]:
    """Return the subset of ``paths`` that violate the block-list.

    Used by both ``__main__`` and the test suite. Pure: no I/O, no exit.
    """
    return [p for p in paths if _matches_any(p, BLOCKED_PATTERNS)]


def _get_changed_files_from_gh(pr_number: str, repo: str) -> list[str]:
    """Query ``gh`` for the list of changed files in the PR."""
    result = subprocess.run(
        ["gh", "pr", "diff", pr_number, "--repo", repo, "--name-only"],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if result.returncode != 0:
        print(
            f"path-guard: gh pr diff failed (exit {result.returncode}): "
            f"{result.stderr.strip()}",
            file=sys.stderr,
        )
        sys.exit(2)
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def main() -> int:
    """CLI entry: read PR number from env, query changed files, enforce.

    Required env (set by workflow):

    * ``PR_NUMBER`` — the PR being checked
    * ``GITHUB_REPOSITORY`` — owner/name (GitHub Actions default)

    For testing locally, optionally set ``PATH_GUARD_FILE_LIST`` to a
    newline-separated list of paths to skip the ``gh`` call.
    """
    override = os.environ.get("PATH_GUARD_FILE_LIST")
    if override is not None:
        paths = [line.strip() for line in override.splitlines() if line.strip()]
    else:
        pr_number = os.environ.get("PR_NUMBER")
        repo = os.environ.get("GITHUB_REPOSITORY")
        if not pr_number or not repo:
            print(
                "path-guard: PR_NUMBER and GITHUB_REPOSITORY are required env vars",
                file=sys.stderr,
            )
            return 2
        paths = _get_changed_files_from_gh(pr_number, repo)

    violations = find_blocked_paths(paths)
    if violations:
        print("path-guard: BLOCKED — PR touches off-limits paths:", file=sys.stderr)
        for v in violations:
            print(f"  - {v}", file=sys.stderr)
        print(
            "\nThese paths are protected from agent edits. A human must "
            "open a PR with CODEOWNER review.",
            file=sys.stderr,
        )
        return 1

    print(f"path-guard: OK ({len(paths)} files checked, no violations).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
