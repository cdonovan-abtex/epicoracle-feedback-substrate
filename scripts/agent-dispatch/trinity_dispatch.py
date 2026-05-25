#!/usr/bin/env python3
"""Trinity dispatch — parallel Codex + Gemini critique on suggestion-kind.

Reserved for ambiguous, architectural, or high-blast-radius suggestions.
The triage classifier routes here when:

* ``kind == suggestion`` (always — suggestions get the deeper look)
* ``touched_surface`` is one of {auth, tenancy, deploy, financial}
  regardless of kind
* security_keywords are present

Skeleton for v0.1. Wave B wires Codex (MCP) and Gemini (CLI) clients per
the satellite's existing trinity-on-brief convention. Output of each
critique is posted as a separate issue comment so Christian (and the
fix-pr step) can read both perspectives before any code change.

Per ``feedback_trinity_on_brief``: trinity activates at the brief tier
when blast radius is high or wave introduces a new architectural pattern.
This script is the workflow-level equivalent: it activates the trinity
loop within the agent-dispatch flow on the same conditions.
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
        key_var="CODEX_API_KEY",
        issue_number=issue_number,
        repo=repo,
        step_name="trinity-dispatch (Codex side)",
    ):
        return 0

    if not issue_number:
        print("trinity_dispatch: ISSUE_NUMBER not set", file=sys.stderr)
        return 2

    print(
        f"trinity_dispatch: skeleton — would dispatch Codex + Gemini critiques "
        f"for issue #{issue_number} in parallel",
        file=sys.stderr,
    )

    # Wave B: parallel Codex + Gemini critique → reconcile → post as
    # comments. For v0.1 we leave a placeholder.
    _comment_on_issue(
        issue_number,
        repo,
        "trinity_dispatch skeleton invoked — Wave B will fan out to "
        "Codex + Gemini critiques here.",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
