"""Shared helper: gracefully skip an LLM step when the required API key
isn't configured.

Per the v2 brief's v0.1 scope, LLM-bearing scripts are documented
skeletons. When the agent-dispatch environment doesn't yet have the
relevant API key set, the script must NOT fail the workflow — it should
post a clear audit comment on the issue and exit 0, so the operator's
feedback remains queued and visible without raising spurious red CI.

Christian's intent (2026-05-25): substrate ships live with zero API
secrets required; LLM-backed automation lights up as keys are added.
"""

from __future__ import annotations

import contextlib
import os
import subprocess


def _comment_on_issue(issue_number: str, repo: str, body: str) -> None:
    """Best-effort gh comment; never raises."""
    with contextlib.suppress(Exception):
        subprocess.run(
            ["gh", "issue", "comment", issue_number, "--repo", repo, "--body", body],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )


def skip_if_no_key(
    *,
    key_var: str,
    issue_number: str,
    repo: str,
    step_name: str,
) -> bool:
    """If ``key_var`` env var is unset/empty, post a skip-comment on the
    issue and return True. Caller should exit 0 immediately.

    Returns False if the key is present (caller proceeds normally).
    """
    if os.environ.get(key_var, "").strip():
        return False
    body = (
        f"⏭️ **{step_name}** skipped — `{key_var}` not configured in the "
        f"`agent-dispatch` environment yet.\n\n"
        f"The feedback substrate is live and your submission is queued. "
        f"The LLM-backed automation that would normally process this step "
        f"is gated on the API key being set at the org level. Manual "
        f"triage applies until the key is added.\n\n"
        f"_Per the v2 brief's v0.1 scope, this is expected behavior — "
        f"automation lights up incrementally as keys are configured._"
    )
    if issue_number and repo:
        _comment_on_issue(issue_number, repo, body)
    print(f"[skip_helper] {step_name}: {key_var} not set; exiting 0")
    return True
