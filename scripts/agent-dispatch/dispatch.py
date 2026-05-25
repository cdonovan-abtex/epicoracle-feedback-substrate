#!/usr/bin/env python3
"""Dispatch step — routes a classified issue to the right downstream agent.

Reads the triage step's ``classifier_decision`` from env (set by GH
Actions step output ↔ env) and invokes the matching sibling script:

* ``sandbox`` → ``sandbox_repro.py`` then ``fix_pr.py``
* ``trinity`` → ``trinity_dispatch.py`` then ``fix_pr.py``
* ``answer-draft`` → ``answer_draft.py``
* ``needs-human`` → label-only, no agent action

Each downstream script is invoked as a subprocess. This script enforces
the agent termination ceiling (max 3 attempts per step, per v2 brief)
and labels the issue with ``agent/status:needs-human`` if the ceiling is
hit.

For v0.1 the downstream scripts (sandbox_repro, fix_pr, trinity_dispatch,
answer_draft) are skeletons with documented contracts; their actual
LLM-bearing implementations are wired in Wave B per the v2 brief's
dispatch strategy. This script's job is the routing + ceiling logic,
which is testable today.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# Make sibling _llm_helpers importable when invoked from any cwd
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _llm_helpers import transition_status  # noqa: E402

SCRIPT_DIR = Path(__file__).resolve().parent
MAX_ATTEMPTS = 3
"""Termination ceiling per v2 brief: max 3 attempts per step before
applying ``agent/status:needs-human`` and ending the workflow."""

DECISION_TO_SCRIPT: dict[str, tuple[str, ...]] = {
    "sandbox": ("sandbox_repro.py", "fix_pr.py"),
    "trinity": ("trinity_dispatch.py", "fix_pr.py"),
    "answer-draft": ("answer_draft.py",),
    "needs-human": (),
}


def _label_issue(issue_number: str, label: str) -> None:
    """Transition the agent/status:* label atomically (remove all other
    status labels first, then add the target). Best-effort.

    v0.2.0a5: delegates to _llm_helpers.transition_status so the v0.1.x
    label-accumulation bug (queued + processing + fix-ready all stuck) is
    fixed at the orchestrator layer too, not just inside answer_draft/fix_pr.
    """
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not (issue_number and repo):
        return
    try:
        transition_status(issue_number=issue_number, repo=repo, to_label=label)
    except ValueError:
        # transition_status only accepts known agent/status:* labels; for any
        # other label (legacy flat ones, etc.) fall back to plain add.
        subprocess.run(
            ["gh", "issue", "edit", issue_number, "--repo", repo,
             "--add-label", label],
            capture_output=True, check=False, timeout=15,
        )


def _comment_on_issue(issue_number: str, body: str) -> None:
    """Post a comment on the issue. Best-effort."""
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not (issue_number and repo):
        return
    subprocess.run(
        ["gh", "issue", "comment", issue_number, "--repo", repo, "--body", body],
        capture_output=True,
        check=False,
        timeout=15,
    )


def _run_step(script: str) -> int:
    """Invoke a sibling script; return its exit code."""
    path = SCRIPT_DIR / script
    if not path.exists():
        print(f"dispatch: script not found: {path}", file=sys.stderr)
        return 127
    result = subprocess.run(
        [sys.executable, str(path)],
        check=False,
        timeout=600,
    )
    return result.returncode


def _run_with_ceiling(script: str, issue_number: str) -> int:
    """Run ``script`` up to MAX_ATTEMPTS times; return last exit code."""
    last_rc = 0
    for attempt in range(1, MAX_ATTEMPTS + 1):
        print(f"dispatch: {script} attempt {attempt}/{MAX_ATTEMPTS}", file=sys.stderr)
        last_rc = _run_step(script)
        if last_rc == 0:
            return 0
    _label_issue(issue_number, "agent/status:needs-human")
    _comment_on_issue(
        issue_number,
        f"I'm stuck after {MAX_ATTEMPTS} attempts on `{script}` "
        "(termination ceiling). Marking `agent/status:needs-human`.",
    )
    return last_rc


def main() -> int:
    decision = os.environ.get("CLASSIFIER_DECISION", "").strip()
    issue_number = os.environ.get("ISSUE_NUMBER", "").strip()

    if not decision:
        print("dispatch: CLASSIFIER_DECISION env empty", file=sys.stderr)
        return 2

    print(f"dispatch: decision={decision} issue={issue_number}", file=sys.stderr)

    if decision == "needs-human":
        _label_issue(issue_number, "agent/status:needs-human")
        return 0

    scripts = DECISION_TO_SCRIPT.get(decision)
    if scripts is None:
        print(f"dispatch: unknown decision {decision!r}", file=sys.stderr)
        _label_issue(issue_number, "agent/status:needs-human")
        return 2

    _label_issue(issue_number, "agent/status:processing")
    for script in scripts:
        rc = _run_with_ceiling(script, issue_number)
        if rc != 0:
            return rc

    _label_issue(issue_number, "agent/status:fix-ready")
    return 0


if __name__ == "__main__":
    sys.exit(main())
