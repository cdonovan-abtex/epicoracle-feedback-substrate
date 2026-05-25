"""Idempotency check tests — uses ``httpx.MockTransport`` for offline fidelity.

The substrate's idempotency check searches GitHub for an existing issue
carrying a given submission_id. Failure modes:

* HTTP 200 with one item → return its issue number (hit)
* HTTP 200 with empty items → return None (miss)
* HTTP 5xx / 4xx → return None (best-effort)
* Network error → return None (best-effort)
* Malformed JSON → return None (best-effort)

The check must NEVER raise — the dispatcher relies on a None return to
mean "proceed to create" and a None return on any failure ensures
submissions are never dropped because of a flaky search API.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from uuid import uuid4

import httpx
import pytest

from epicoracle_feedback import check_idempotency


def _mock_client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_returns_issue_number_on_hit() -> None:
    sub_id = uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
        assert "search/issues" in str(request.url)
        assert str(sub_id) in str(request.url)
        return httpx.Response(
            200,
            json={
                "total_count": 1,
                "items": [{"number": 42, "html_url": "https://x"}],
            },
        )

    with _mock_client(handler) as c:
        result = check_idempotency("cdonovan-abtex/foo", sub_id, client=c)
    assert result == 42


def test_returns_none_on_miss() -> None:
    def handler(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"total_count": 0, "items": []})

    with _mock_client(handler) as c:
        result = check_idempotency("cdonovan-abtex/foo", uuid4(), client=c)
    assert result is None


def test_returns_none_on_500() -> None:
    def handler(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"message": "Server Error"})

    with _mock_client(handler) as c:
        result = check_idempotency("cdonovan-abtex/foo", uuid4(), client=c)
    assert result is None


def test_returns_none_on_rate_limit() -> None:
    def handler(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "API rate limit exceeded"})

    with _mock_client(handler) as c:
        result = check_idempotency("cdonovan-abtex/foo", uuid4(), client=c)
    assert result is None


def test_returns_none_on_network_error() -> None:
    def handler(_r: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with _mock_client(handler) as c:
        result = check_idempotency("cdonovan-abtex/foo", uuid4(), client=c)
    assert result is None


def test_returns_none_on_malformed_json() -> None:
    def handler(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json")

    with _mock_client(handler) as c:
        result = check_idempotency("cdonovan-abtex/foo", uuid4(), client=c)
    assert result is None


def test_token_passed_as_bearer_header() -> None:
    captured_auth: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_auth.append(request.headers.get("Authorization", ""))
        return httpx.Response(200, json={"items": []})

    with _mock_client(handler) as c:
        check_idempotency(
            "cdonovan-abtex/foo",
            uuid4(),
            gh_token="ghp_test_token_value",
            client=c,
        )
    assert captured_auth[0] == "Bearer ghp_test_token_value"


def test_no_auth_header_when_token_absent() -> None:
    captured_auth: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_auth.append(request.headers.get("Authorization", ""))
        return httpx.Response(200, json={"items": []})

    with _mock_client(handler) as c:
        check_idempotency("cdonovan-abtex/foo", uuid4(), client=c)
    assert captured_auth[0] == ""


def test_query_includes_repo_scope_and_body_search() -> None:
    captured_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_urls.append(str(request.url))
        return httpx.Response(200, json={"items": []})

    with _mock_client(handler) as c:
        check_idempotency("cdonovan-abtex/foo", uuid4(), client=c)

    url = captured_urls[0]
    assert "repo%3Acdonovan-abtex%2Ffoo" in url or "repo:cdonovan-abtex/foo" in url
    assert "in%3Abody" in url or "in:body" in url
    assert "type%3Aissue" in url or "type:issue" in url


@pytest.mark.parametrize("sub_id_input", [uuid4(), str(uuid4())])
def test_accepts_uuid_or_string(sub_id_input: object) -> None:
    """API contract: both UUID objects and their string form work."""

    def handler(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": []})

    with _mock_client(handler) as c:
        result = check_idempotency("cdonovan-abtex/foo", sub_id_input, client=c)  # type: ignore[arg-type]
    assert result is None


def test_returns_none_when_item_lacks_number_field() -> None:
    """Defensive: GitHub response shape changed — don't crash."""

    def handler(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": [{"id": 1234567}]})

    with _mock_client(handler) as c:
        result = check_idempotency("cdonovan-abtex/foo", uuid4(), client=c)
    assert result is None


def test_only_first_result_consulted() -> None:
    """GitHub may return multiple matches; we only care about the first."""

    def handler(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=json.dumps(
                {"items": [{"number": 1}, {"number": 2}, {"number": 3}]},
            ).encode(),
        )

    with _mock_client(handler) as c:
        result = check_idempotency("cdonovan-abtex/foo", uuid4(), client=c)
    assert result == 1
