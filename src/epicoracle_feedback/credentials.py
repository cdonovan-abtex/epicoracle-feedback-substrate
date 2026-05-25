"""Server-side credential-pattern scan.

Why this exists: an operator pasting a stack trace can accidentally include
an AWS key, an OpenAI key, or a GitHub PAT. Once that text lands on
github.com it's secret-scanning-detectable (good) but also crawler-visible
during the window between create and revoke (bad). The cheapest defence is
a regex scan at the router that rejects with HTTP 400 before the dispatcher
ever sees the body.

This is NOT a substitute for GitHub's own secret scanning. It is a
defense-in-depth check that catches the high-signal patterns we know about.
False negatives (some bespoke vendor key format) fall through; GitHub's
scanner catches those at rest.

Both Codex and Gemini's BLOCKERs on the v0 brief converged on "private
repo storage is not privacy by itself" — this is one of the two controls
(the other being labels for sensitivity classification) that closes that gap.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class CredentialPattern:
    """One credential format we know how to detect."""

    name: str
    pattern: re.Pattern[str]
    description: str


# Patterns are anchored where possible to reduce false positives.
# Order matters only insofar as the more-specific patterns appear first so
# the returned list reads cleanly for the operator-facing error message.
_PATTERNS: Final[tuple[CredentialPattern, ...]] = (
    CredentialPattern(
        name="aws_access_key_id",
        # AKIA / ASIA / AGPA / AIDA prefixes, 16 alnum chars.
        pattern=re.compile(r"\b(?:AKIA|ASIA|AGPA|AIDA|AROA|AIPA|ANPA|ANVA)[0-9A-Z]{16}\b"),
        description="AWS access key id (AKIA/ASIA/AIDA/...)",
    ),
    CredentialPattern(
        name="aws_secret_access_key",
        # Heuristic: AWS_SECRET_ACCESS_KEY in proximity to a 40-char base64-ish blob.
        pattern=re.compile(
            r"(?i)aws[_-]?(secret|sk)[_-]?(access[_-]?)?key[\"' :=]{1,5}[A-Za-z0-9/+=]{40}",
        ),
        description="AWS secret access key",
    ),
    CredentialPattern(
        name="anthropic_api_key",
        pattern=re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b"),
        description="Anthropic API key (sk-ant-...)",
    ),
    CredentialPattern(
        name="openai_api_key",
        # Modern keys are sk-proj- / sk-svcacct- with long suffixes; classic
        # sk- format too. Require minimum length to avoid the false-positive
        # on a literal "sk-test" in documentation.
        pattern=re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{30,}\b"),
        description="OpenAI API key (sk- / sk-proj- / sk-svcacct-)",
    ),
    CredentialPattern(
        name="github_pat_classic",
        pattern=re.compile(r"\bghp_[A-Za-z0-9]{30,}\b"),
        description="GitHub classic personal access token (ghp_...)",
    ),
    CredentialPattern(
        name="github_pat_fine_grained",
        pattern=re.compile(r"\bgithub_pat_[A-Za-z0-9_]{30,}\b"),
        description="GitHub fine-grained personal access token (github_pat_...)",
    ),
    CredentialPattern(
        name="github_oauth_token",
        pattern=re.compile(r"\bgho_[A-Za-z0-9]{30,}\b"),
        description="GitHub OAuth token (gho_...)",
    ),
    CredentialPattern(
        name="github_app_install_token",
        pattern=re.compile(r"\bghs_[A-Za-z0-9]{30,}\b"),
        description="GitHub App installation token (ghs_...)",
    ),
    CredentialPattern(
        name="slack_token",
        pattern=re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{20,}\b"),
        description="Slack token (xoxb-/xoxa-/xoxp-/...)",
    ),
    CredentialPattern(
        name="google_api_key",
        pattern=re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
        description="Google API key (AIza...)",
    ),
    CredentialPattern(
        name="stripe_secret_key",
        pattern=re.compile(r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{20,}\b"),
        description="Stripe secret/restricted key",
    ),
    CredentialPattern(
        name="private_key_block",
        pattern=re.compile(
            r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----",
        ),
        description="PEM-encoded private key block",
    ),
    CredentialPattern(
        name="jwt_token",
        # Three base64url segments separated by dots; first must decode to
        # a JOSE header. Conservative length minima reduce noise.
        pattern=re.compile(
            r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b",
        ),
        description="JWT (eyJ... header)",
    ),
)


def scan_for_credentials(text: str) -> list[str]:
    """Return the list of credential-pattern names found in ``text``.

    Empty list means "no known credential pattern matched". A non-empty list
    means the caller MUST reject the submission (HTTP 400 at the router
    layer). The names returned are stable identifiers suitable for logging,
    structured events, and the operator-facing error message —
    ``description`` would leak detection heuristics in error responses.

    The function is intentionally pure and side-effect-free: no logging, no
    metric emission, no truncation of the input. The caller decides what to
    do with the finding.

    Performance note: each pattern is applied to the full string with
    ``re.search``. For 5KB max-length feedback bodies this is microseconds;
    the dispatcher's GitHub round-trip dominates by orders of magnitude.
    """
    if not text:
        return []
    return [p.name for p in _PATTERNS if p.pattern.search(text)]


def list_known_patterns() -> tuple[str, ...]:
    """Names of all credential patterns the scanner knows about.

    Exposed for documentation/test reasons. Not part of the hot path.
    """
    return tuple(p.name for p in _PATTERNS)
