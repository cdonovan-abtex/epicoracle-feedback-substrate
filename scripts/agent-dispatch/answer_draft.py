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
