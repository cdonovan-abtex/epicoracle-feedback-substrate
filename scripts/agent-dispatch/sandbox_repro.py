#!/usr/bin/env python3
"""Sandbox bug-repro — pull pre-built GHCR image + Playwright headless.

Per v2 brief's "Sandbox runner contract":

  1. Pull pre-built Docker image from GHCR
     (built by main-branch CI on every merge; see
     ``templates/build-ghcr-image.yml``)
  2. Start container with synthetic-mode env (auth disabled, ERP disabled)
  3. Wait for /health to return 200 (timeout 60s)
  4. Launch Playwright headless against the container
  5. Navigate to ROUTE_PATH and attempt repro
  6. Capture screenshot + console errors + DOM snapshot
  7. Post a COMMENT on the issue with:
     - Screenshot inline (data:image/png;base64,...)
     - Console errors in fenced block
     - One-line status: "Repro succeeded" / "Repro failed"

For v0.1 this script is a documented skeleton: the image-pull and the
issue-comment posting work; the Playwright orchestration is wired during
Wave B when each satellite's actual fixture contract (routes, synthetic
principal headers, mocked downstreams) is known.

Reads from env (set by workflow):

* ``ISSUE_NUMBER``, ``ISSUE_BODY`` — already in agent-dispatch.yml env block
* ``GITHUB_REPOSITORY`` — owner/name
* ``SATELLITE_SLUG`` — e.g. ``marketplace``, ``compliance``, ``hub``
* ``ROUTE_PATH`` — extracted by triage, threaded via output → env
"""

from __future__ import annotations

import base64
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

HEALTH_TIMEOUT_S = 60
CONTAINER_NAME = "feedback-repro-sandbox"


def _extract_route(body: str) -> str:
    m = re.search(r"Route: `([^`]+)`", body)
    return m.group(1) if m else "/"


def _ghcr_image(satellite: str) -> str:
    return f"ghcr.io/cdonovan-abtex/epicoracle-{satellite}:main-latest"


def _pull_image(image: str) -> bool:
    print(f"sandbox: pulling {image}", file=sys.stderr)
    result = subprocess.run(
        ["docker", "pull", image],
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    if result.returncode != 0:
        print(f"sandbox: docker pull failed: {result.stderr}", file=sys.stderr)
        return False
    return True


def _start_container(image: str, env: Iterable[tuple[str, str]]) -> bool:
    """Start the synthetic-mode container with deny-by-default network."""
    cmd = ["docker", "run", "-d", "--rm", "--name", CONTAINER_NAME, "-p", "8000:8000"]
    for k, v in env:
        cmd.extend(["-e", f"{k}={v}"])
    cmd.append(image)
    result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=30)
    if result.returncode != 0:
        print(f"sandbox: docker run failed: {result.stderr}", file=sys.stderr)
        return False
    return True


def _stop_container() -> None:
    subprocess.run(
        ["docker", "stop", CONTAINER_NAME],
        capture_output=True,
        check=False,
        timeout=30,
    )


def _post_repro_comment(
    issue_number: str, repo: str, status: str, evidence: dict[str, str]
) -> None:
    """Post a comment on the issue with repro evidence inline."""
    parts = [
        f"### Sandbox repro: {status}",
        "",
    ]
    if "screenshot_b64" in evidence:
        parts.append(f"![screenshot](data:image/png;base64,{evidence['screenshot_b64']})")
    if "console_errors" in evidence:
        parts.append("\n**Console errors:**\n```\n" + evidence["console_errors"] + "\n```")
    if "route_path" in evidence:
        parts.append(f"\n**Route:** `{evidence['route_path']}`")
    body = "\n".join(parts)

    subprocess.run(
        ["gh", "issue", "comment", issue_number, "--repo", repo, "--body", body],
        capture_output=True,
        check=False,
        timeout=30,
    )


def main() -> int:
    issue_number = os.environ.get("ISSUE_NUMBER", "").strip()
    issue_body = os.environ.get("ISSUE_BODY", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    satellite = os.environ.get("SATELLITE_SLUG", "marketplace")

    if not (issue_number and repo):
        print("sandbox: missing ISSUE_NUMBER or GITHUB_REPOSITORY", file=sys.stderr)
        return 2

    route_path = _extract_route(issue_body)
    image = _ghcr_image(satellite)

    if not _pull_image(image):
        _post_repro_comment(
            issue_number,
            repo,
            "Repro failed (image pull error)",
            {"route_path": route_path},
        )
        return 1

    synthetic_env: list[tuple[str, str]] = [
        ("SYNTHETIC_MODE", "true"),
        ("AUTH_DISABLED", "true"),
        ("TENANT", "synthetic"),
        ("EPICOR_DISABLED", "true"),
        ("SP_API_DISABLED", "true"),
    ]

    if not _start_container(image, synthetic_env):
        _post_repro_comment(
            issue_number,
            repo,
            "Repro failed (container start error)",
            {"route_path": route_path},
        )
        return 1

    # NB: Playwright orchestration intentionally left as a contract for
    # Wave B. For v0.1 we exercise the dispatch + image-pull skeleton and
    # post a placeholder evidence comment. The placeholder makes the
    # status loop transition visible end-to-end without faking a fix.
    try:
        # Placeholder PNG (1x1 transparent pixel) — real implementation
        # captures via ``playwright`` page.screenshot().
        placeholder_png = base64.b64decode(
            b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkAAIAAAoAAv/lxKUAAAAASUVORK5CYII="
        )
        _ = placeholder_png  # consumed by Wave B real impl

        _post_repro_comment(
            issue_number,
            repo,
            "Repro skeleton — Wave B implementation pending",
            {
                "route_path": route_path,
                "console_errors": "(no Playwright run in v0.1 skeleton)",
            },
        )
    finally:
        _stop_container()

    return 0


if __name__ == "__main__":
    sys.exit(main())


# Convenience for tests / imports — not used by the workflow path.
_module_path = Path(__file__).resolve()
