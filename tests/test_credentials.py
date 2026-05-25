"""Credential-pattern scanner tests.

Tests are written against the API contract (``scan_for_credentials`` returns
a list of pattern names), not against specific regex internals — that lets
us tighten the regexes over time without churn in the test file.

All "secret" strings here are SYNTHETIC and deliberately malformed where
possible (e.g. ``AKIA`` followed by deterministic non-secret characters).
GitHub secret scanning will not match these.
"""

from __future__ import annotations

import pytest

from epicoracle_feedback import scan_for_credentials
from epicoracle_feedback.credentials import list_known_patterns

# Synthetic test fixtures — none of these are real credentials.
# The ``# nosec`` markers signal to scanners that these are intentional.

SYNTHETIC_AWS_KEY = "AKIAIOSFODNN7EXAMPLE"  # AWS docs example, public  # nosec
SYNTHETIC_AWS_SECRET = "aws_secret_access_key=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"  # nosec
SYNTHETIC_ANTHROPIC = "sk-ant-api03-AAAAAAAAAAAAAAAAAAAA"  # nosec
SYNTHETIC_OPENAI = "sk-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"  # nosec
SYNTHETIC_OPENAI_PROJ = "sk-proj-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"  # nosec
SYNTHETIC_GH_PAT = "ghp_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"  # nosec
SYNTHETIC_GH_PAT_FG = "github_pat_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"  # nosec
SYNTHETIC_GH_OAUTH = "gho_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"  # nosec
SYNTHETIC_GH_APP_INSTALL = "ghs_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"  # nosec
SYNTHETIC_SLACK = "xoxb-AAAAAAAAAAAAAAAAAAAA"  # nosec
SYNTHETIC_GOOGLE = "AIzaAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"  # nosec
SYNTHETIC_STRIPE = "sk_live_AAAAAAAAAAAAAAAAAAAAAAAA"  # nosec
SYNTHETIC_PRIVATE_KEY = "-----BEGIN RSA PRIVATE KEY-----\nAAAA"  # nosec
SYNTHETIC_JWT = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0."
    "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
)


def test_empty_string_returns_empty_list() -> None:
    assert scan_for_credentials("") == []


def test_clean_bug_report_returns_empty_list() -> None:
    body = (
        "When I click the Push button on /tracking with no carrier, "
        "I get a 500 error. The toast says 'Internal Server Error'."
    )
    assert scan_for_credentials(body) == []


@pytest.mark.parametrize(
    ("credential", "expected_name"),
    [
        (SYNTHETIC_AWS_KEY, "aws_access_key_id"),
        (SYNTHETIC_AWS_SECRET, "aws_secret_access_key"),
        (SYNTHETIC_ANTHROPIC, "anthropic_api_key"),
        (SYNTHETIC_OPENAI, "openai_api_key"),
        (SYNTHETIC_OPENAI_PROJ, "openai_api_key"),
        (SYNTHETIC_GH_PAT, "github_pat_classic"),
        (SYNTHETIC_GH_PAT_FG, "github_pat_fine_grained"),
        (SYNTHETIC_GH_OAUTH, "github_oauth_token"),
        (SYNTHETIC_GH_APP_INSTALL, "github_app_install_token"),
        (SYNTHETIC_SLACK, "slack_token"),
        (SYNTHETIC_GOOGLE, "google_api_key"),
        (SYNTHETIC_STRIPE, "stripe_secret_key"),
        (SYNTHETIC_PRIVATE_KEY, "private_key_block"),
        (SYNTHETIC_JWT, "jwt_token"),
    ],
)
def test_detects_known_patterns(credential: str, expected_name: str) -> None:
    body = f"Here's a debug dump:\n{credential}\nand here's more text."
    findings = scan_for_credentials(body)
    assert expected_name in findings, (
        f"Expected to detect {expected_name} in body containing {credential!r}, "
        f"got: {findings}"
    )


def test_detects_multiple_credentials_in_one_body() -> None:
    body = f"{SYNTHETIC_AWS_KEY} and {SYNTHETIC_ANTHROPIC} and {SYNTHETIC_GH_PAT}"
    findings = scan_for_credentials(body)
    assert "aws_access_key_id" in findings
    assert "anthropic_api_key" in findings
    assert "github_pat_classic" in findings


def test_does_not_false_positive_on_short_docs_example() -> None:
    """``sk-test`` literal in documentation must not trigger the OpenAI pattern."""
    body = "Use sk-test for testing"
    findings = scan_for_credentials(body)
    # Note: the OpenAI key pattern requires 30+ chars after the prefix; ``sk-test``
    # is far below that threshold and must not match.
    assert "openai_api_key" not in findings


def test_does_not_false_positive_on_uuid_lookalikes() -> None:
    """UUIDs in bug reports are common and must not trigger any pattern."""
    body = (
        "Reproducer: submission_id 12345678-1234-5678-1234-567812345678 "
        "shows wrong status on the tracking page."
    )
    assert scan_for_credentials(body) == []


def test_list_known_patterns_returns_non_empty() -> None:
    """Smoke test that the canonical pattern list is exposed for docs/tests."""
    names = list_known_patterns()
    assert len(names) > 5
    assert "aws_access_key_id" in names
    assert "anthropic_api_key" in names
    assert "github_pat_classic" in names
