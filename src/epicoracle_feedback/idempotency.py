"""Idempotency check — has an issue already been filed for this submission_id?

Both trinity reviewers (Codex + Gemini, independently) called out the
double-create risk in the JSONL replay path: an operator's network blips,
the dispatcher fails-soft to JSONL, network comes back, replay creates the
issue, but the dispatcher's first call also wrote a record and retry
arrives later → two issues for one submission.

The fix is a search-before-create against GitHub's search-issues API,
keyed on the client-generated ``submission_id``. The dispatcher calls this
helper before invoking ``gh issue create``; the replay script calls it
before flushing each JSONL record.

We embed the ``submission_id`` in the issue body inside a hidden
machine-readable JSON block (see ``dispatch._render_issue_body``) and
search for it as a body substring. This is more reliable than a label
because GitHub's search index covers issue bodies and we don't have to
worry about label-cardinality issues.

We use ``httpx`` (not the ``gh`` CLI) here because:

* Search is read-only and benefits from connection reuse.
* The dispatcher's ``gh`` shell-out is justified by reusing host auth on
  dev machines; search-before-create runs on every submit and the latency
  of spawning a subprocess each time is undesirable.

If GitHub returns 5xx, rate-limits, or the network is down, this helper
returns ``None`` (caller proceeds to create — preferring a duplicate to a
dropped submission). Failure here is logged but never raised.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from uuid import UUID

logger = logging.getLogger(__name__)


_SEARCH_URL = "https://api.github.com/search/issues"
_GITHUB_API_VERSION = "2022-11-28"
_HTTP_TIMEOUT_S = 5.0
"""Read-only search timeout. Tuned to be tight — if GitHub is slow enough
that we time out, we'd rather risk a duplicate issue than block the
operator-facing submit modal."""


def check_idempotency(
    repo: str,
    submission_id: UUID | str,
    *,
    gh_token: str | None = None,
    client: httpx.Client | None = None,
) -> int | None:
    """Search GitHub for an existing issue carrying ``submission_id``.

    Returns the issue number on hit, ``None`` on miss or on any failure
    (network, rate-limit, parse error). The caller must treat ``None`` as
    "no prior issue found, proceed to create" — never as "search failed,
    abort". Aborting on search-failure would silently drop submissions
    when GitHub has a bad afternoon.

    Parameters
    ----------
    repo
        ``owner/name`` repo to scope the search.
    submission_id
        Client-generated identifier from ``FeedbackPayload``. UUID or its
        canonical string form both accepted; we always serialize as the
        canonical 8-4-4-4-12 lowercase string.
    gh_token
        Optional bearer token for the GitHub search API. When None, the
        request is anonymous (lower rate-limit budget but works on dev).
    client
        Optional pre-constructed ``httpx.Client`` (tests inject a
        ``MockTransport``-backed client). When None, a transient client is
        constructed and closed on return.
    """
    sub_id_str = str(submission_id).lower()
    # Match the canonical 36-char form anywhere in the issue body. Using
    # the bare UUID is safe — collision probability is negligible.
    query = f'repo:{repo} type:issue in:body "{sub_id_str}"'
    params = {"q": query, "per_page": "1"}
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": _GITHUB_API_VERSION,
    }
    if gh_token:
        headers["Authorization"] = f"Bearer {gh_token}"

    owns_client = client is None
    http = client or httpx.Client(timeout=_HTTP_TIMEOUT_S)
    try:
        response = http.get(_SEARCH_URL, params=params, headers=headers)
    except httpx.HTTPError as exc:
        logger.info(
            "idempotency check failed (network) for submission_id=%s: %s",
            sub_id_str,
            exc,
        )
        return None
    finally:
        if owns_client:
            http.close()

    if response.status_code != 200:
        logger.info(
            "idempotency check non-200 for submission_id=%s: %s",
            sub_id_str,
            response.status_code,
        )
        return None

    try:
        data = response.json()
    except ValueError as exc:
        logger.info(
            "idempotency check json-decode failed for submission_id=%s: %s",
            sub_id_str,
            exc,
        )
        return None

    items = data.get("items") or []
    if not items:
        return None

    first = items[0]
    number = first.get("number")
    if isinstance(number, int):
        return number
    return None
