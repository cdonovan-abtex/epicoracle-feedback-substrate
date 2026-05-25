#!/usr/bin/env python3
"""Fix-PR step — invokes Codex to draft a fix and open a PR.

Skeleton for v0.1. The Codex invocation contract is intentionally separate
from the substrate's own concerns (the substrate cares about *dispatch*,
not about *which LLM is doing the editing*). Wave B wires the Codex MCP
session per the satellite's existing editor-agent integration.

Contract:

* Reads ``ISSUE_NUMBER``, ``ISSUE_BODY``, ``ISSUE_TITLE`` from env.
* Reads classification from ``CLASSIFICATION`` env (JSON).
* Opens a branch named ``feedback/<issue_number>-<slug>``.
* Invokes Codex with:
  - The issue body wrapped in fenced data block + "data not instruction"
    preamble (same boundary as the issue body itself).
  - The classification.
  - Path-allowlist (passed to Codex as a constraint).
* On Codex success: ``git push`` + ``gh pr create --base main`` with
  ``Closes #<issue>`` in body and inline repro evidence link.
* Posts the PR URL as an issue comment.

For v0.1 the script is a documented skeleton; Wave B integrates the
Codex client. The path-guard step in the workflow validates the resulting
PR independently of whatever Codex produced.
"""

from __future__ import annotations

import json
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
    classification_raw = os.environ.get("CLASSIFICATION", "{}")

    try:
        classification = json.loads(classification_raw)
    except json.JSONDecodeError:
        classification = {}

    if not issue_number:
        print("fix-pr: ISSUE_NUMBER not set", file=sys.stderr)
        return 2

    decision = classification.get("classifier_decision", "unknown")
    print(
        f"fix-pr: skeleton — would open PR for issue #{issue_number} "
        f"(decision={decision})",
        file=sys.stderr,
    )

    # Wave B: invoke Codex with the issue context, write a branch, push,
    # and open a PR. For now we just leave a status comment so the
    # workflow's end-to-end transitions are visible.
    _comment_on_issue(
        issue_number,
        repo,
        "fix-pr skeleton invoked — Wave B will wire Codex here.",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
