#!/usr/bin/env python3
"""Answer-draft step — Claude one-shot answer on question-kind feedback.

When the operator submits a ``kind=question``, the triage classifier
routes here. Claude reads the issue body and drafts an answer comment;
the issue is then labeled ``agent/status:fix-ready`` (not auto-closed —
per v2 brief, questions stay open until a human acts so operators see
their question is acknowledged).

Skeleton for v0.1. Wave B wires the Anthropic SDK client and a
context-injection pattern that includes the satellite's relevant docs
(README, runbook, CHANGELOG) as Claude context.
"""

from __future__ import annotations

import os
import subprocess
import sys

# Make the sibling _skip_helper importable when invoked from any cwd
sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent))
from _skip_helper import skip_if_no_key  # noqa: E402


def _comment_on_issue(issue_number: str, repo: str, body: str) -> None:
    subprocess.run(
        ["gh", "issue", "comment", issue_number, "--repo", repo, "--body", body],
        capture_output=True,
        check=False,
        timeout=30,
    )


def main() -> int:
    issue_number = os.environ.get("ISSUE_NUMBER", "").strip()
    repo = os.environ.get("GITHUB_REPOSITORY", "")

    # v0.1 graceful-skip: if the LLM API key isn't configured yet, log + exit 0
    if skip_if_no_key(
        key_var="ANTHROPIC_API_KEY",
        issue_number=issue_number,
        repo=repo,
        step_name="answer-draft",
    ):
        return 0

    if not issue_number:
        print("answer_draft: ISSUE_NUMBER not set", file=sys.stderr)
        return 2

    print(
        f"answer_draft: skeleton — would draft answer comment for issue "
        f"#{issue_number}",
        file=sys.stderr,
    )

    _comment_on_issue(
        issue_number,
        repo,
        "answer_draft skeleton invoked — Wave B will wire Claude one-shot here.",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
