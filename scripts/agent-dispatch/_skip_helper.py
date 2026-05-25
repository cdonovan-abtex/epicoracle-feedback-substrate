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
    """If ``key_var`` env var is unset/empty, log + return True.
    Caller should exit 0 immediately.

    Returns False if the key is present (caller proceeds normally).

    v0.2.0a5: silent skip — does NOT post an issue comment anymore.
    Earlier behavior posted a comment per skip, which combined with
    dispatch retries and label-change re-fires produced 16+ bot
    comments per issue (= 16+ emails to the issue author). The audit
    trail is in the workflow run log; the issue thread stays clean.

    Repo + issue_number kept in the signature for API stability +
    potential future use (e.g., when a configurable "verbose" mode
    surfaces skips to operators).
    """
    del issue_number, repo  # intentionally unused after v0.2.0a5 silencing
    if os.environ.get(key_var, "").strip():
        return False
    print(f"[skip_helper] {step_name}: {key_var} not set; exiting 0 (silent)")
    return True
