"""Triage classifier tests.

The classifier is pure: ``classify(title=..., body=...) -> dict``. Tests
verify routing matrix:

* question → answer-draft
* bug + high-risk surface → trinity
* bug + low-risk surface → sandbox
* suggestion → trinity (always)
* security keyword → trinity regardless of kind
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest


def _load_triage() -> Any:
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "scripts" / "agent-dispatch" / "triage.py"
    spec = importlib.util.spec_from_file_location("triage", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["triage"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def triage() -> Any:
    return _load_triage()


def _body(kind: str, route: str, extra: str = "") -> str:
    return (
        f"```\nOperator content here. {extra}\n```\n"
        "---\n"
        f"- Route: `{route}`\n"
        "<!-- MACHINE-READABLE -->\n"
        f'```json\n{{"kind": "{kind}", "route_path": "{route}"}}\n```\n'
    )


def test_question_routes_to_answer_draft(triage: Any) -> None:
    result = triage.classify(
        title="[hub][question] How do I export?",
        body=_body("question", "/help"),
    )
    assert result["kind"] == "question"
    assert result["classifier_decision"] == "answer-draft"


def test_bug_on_auth_surface_routes_to_trinity(triage: Any) -> None:
    result = triage.classify(
        title="[hub][bug] Login broken",
        body=_body("bug", "/login", "session permission expired"),
    )
    assert result["touched_surface"] == "auth"
    assert result["classifier_decision"] == "trinity"


def test_bug_on_ui_surface_routes_to_sandbox(triage: Any) -> None:
    result = triage.classify(
        title="[marketplace][bug] Modal misaligned",
        body=_body("bug", "/products", "modal renders below button"),
    )
    assert result["classifier_decision"] == "sandbox"


def test_suggestion_always_routes_to_trinity(triage: Any) -> None:
    result = triage.classify(
        title="[marketplace][suggestion] Add filter to /products",
        body=_body("suggestion", "/products", "button to filter"),
    )
    assert result["classifier_decision"] == "trinity"


def test_security_keyword_escalates_to_trinity(triage: Any) -> None:
    result = triage.classify(
        title="[marketplace][bug] csrf token issue",
        body=_body("bug", "/checkout", "csrf token mismatch on submit"),
    )
    assert "csrf" in result["security_keywords"]
    assert result["classifier_decision"] == "trinity"


def test_missing_machine_json_defaults_to_bug(triage: Any) -> None:
    body = "Plain body with no machine-readable JSON.\nRoute: `/whatever`"
    result = triage.classify(title="x", body=body)
    assert result["kind"] == "bug"


def test_financial_surface_escalates_to_trinity(triage: Any) -> None:
    result = triage.classify(
        title="[marketplace][bug] invoice margin wrong",
        body=_body("bug", "/invoices", "margin shown on invoice is wrong"),
    )
    assert result["touched_surface"] == "financial"
    assert result["classifier_decision"] == "trinity"
