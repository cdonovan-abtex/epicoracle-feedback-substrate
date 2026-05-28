from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

from epicoracle_feedback.access_log_store import SqliteAccessLogStore
from epicoracle_feedback.schemas.observability import AccessLogEntry


def _entry(index: int, *, tenant: str = "pilot") -> AccessLogEntry:
    return AccessLogEntry(
        correlation_id=f"corr-{index}",
        timestamp_utc=datetime(2026, 5, 27, 12, 0, tzinfo=UTC) + timedelta(seconds=index),
        principal=f"user-{index % 4}@example.test",
        method="GET",
        route_template="/items/{item_id}",
        status=200,
        duration_ms=index % 20,
        response_size_bytes=None,
        tenant=tenant,
        client_ip="100.64.0.2",
    )


def test_sqlite_wal_concurrent_writers(tmp_path) -> None:
    path = tmp_path / "access_log.sqlite"
    store_a = SqliteAccessLogStore(path)
    store_b = SqliteAccessLogStore(path)

    def write_range(start: int) -> None:
        store = store_a if start == 0 else store_b
        for i in range(start, start + 1000):
            store.write_entry(_entry(i))

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(write_range, (0, 1000)))

    assert store_a.count(tenant="pilot") == 2000


def test_retention_prunes_oldest_entries(tmp_path) -> None:
    store = SqliteAccessLogStore(
        tmp_path / "access_log.sqlite",
        max_entries=3,
        max_bytes=10_000_000,
    )
    for i in range(5):
        store.write_entry(_entry(i))

    page = store.query(tenant="pilot", page_size=10)

    assert page.total_count == 3
    assert {entry.correlation_id for entry in page.entries} == {"corr-2", "corr-3", "corr-4"}
