#!/usr/bin/env python3
"""Sandbox bug-repro — GHCR pull stays disabled while migration is deferred.

Future activation (Captain-authorized only) uses the repository basename as
package identity by default, or an explicit package name for a deliberate
mismatch. Private authenticated pulls require ``packages: read`` and exact
repository/package access, with the publisher labeling
``org.opencontainers.image.source``.

Current behavior is intentionally inert unless ``GHCR_SANDBOX_ENABLED`` is
opted in. When disabled, the script exits 0 without pulling or starting a
container.
"""

from __future__ import annotations

import base64
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from epicoracle_feedback import GHCR_PACKAGE_NAME_ENV, GHCR_SANDBOX_ENABLED_ENV
from epicoracle_feedback.ghcr import resolve_ghcr_image, sandbox_pull_enabled

if TYPE_CHECKING:
    from collections.abc import Iterable

HEALTH_TIMEOUT_S = 60
CONTAINER_NAME = "feedback-repro-sandbox"


def _extract_route(body: str) -> str:
    m = re.search(r"Route: `([^`]+)`", body)
    return m.group(1) if m else "/"


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


def main() -> int:  # noqa: PLR0912
    if not sandbox_pull_enabled(os.environ.get(GHCR_SANDBOX_ENABLED_ENV)):
        print(
            "sandbox: GHCR pull disabled while migration is deferred; skipping image pull",
            file=sys.stderr,
        )
        return 0

    issue_number = os.environ.get("ISSUE_NUMBER", "").strip()
    issue_body = os.environ.get("ISSUE_BODY", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    package_name_raw = os.environ.get(GHCR_PACKAGE_NAME_ENV)
    package_name = None if package_name_raw is None else package_name_raw.strip()

    # v0.1 graceful-skip: if the LLM API key isn't configured yet, log + exit 0
    sys.path.insert(0, str(Path(__file__).parent))
    from _skip_helper import skip_if_no_key  # noqa: PLC0415

    if skip_if_no_key(
        key_var="CODEX_API_KEY",
        issue_number=issue_number,
        repo=repo,
        step_name="sandbox-repro",
    ):
        return 0

    rc = 0
    if not (issue_number and repo):
        print("sandbox: missing ISSUE_NUMBER or GITHUB_REPOSITORY", file=sys.stderr)
        rc = 2
    else:
        route_path = _extract_route(issue_body)
        if package_name_raw is not None and not package_name:
            print("sandbox: GHCR package name is empty", file=sys.stderr)
            rc = 2
        else:
            try:
                image = resolve_ghcr_image(repo, package_name=package_name)
            except ValueError as exc:
                print(f"sandbox: invalid GHCR package identity: {exc}", file=sys.stderr)
                rc = 2
            else:
                if not _pull_image(image):
                    # v0.2.0a5: silent on per-attempt failures. dispatch.py retries this
                    # up to MAX_ATTEMPTS and posts ONE summary bail-comment if all attempts
                    # fail. Posting per-attempt comments here multiplied the noise (16+
                    # comments per issue → 16+ emails to the issue author).
                    print(
                        f"sandbox: image pull failed for {image} — exiting non-zero (silent)",
                        file=sys.stderr,
                    )
                    rc = 1
                else:
                    synthetic_env: list[tuple[str, str]] = [
                        ("SYNTHETIC_MODE", "true"),
                        ("AUTH_DISABLED", "true"),
                        ("TENANT", "synthetic"),
                        ("EPICOR_DISABLED", "true"),
                        ("SP_API_DISABLED", "true"),
                    ]

                    if not _start_container(image, synthetic_env):
                        # v0.2.0a5: silent per-attempt — see _pull_image comment above
                        print(
                            "sandbox: container start failed — exiting non-zero (silent)",
                            file=sys.stderr,
                        )
                        rc = 1
                    else:
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

    return rc


if __name__ == "__main__":
    sys.exit(main())


# Convenience for tests / imports — not used by the workflow path.
_module_path = Path(__file__).resolve()
