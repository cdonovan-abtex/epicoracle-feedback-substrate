"""SQLite WAL-backed access-log store."""

from __future__ import annotations

import base64
import json
import os
import sqlite3
import threading
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import quantiles
from typing import Any

from epicoracle_feedback.schemas.observability import (
    AccessLogEntry,
    AccessLogPage,
    AccessLogSummary,
    HttpEvent,
)

DEFAULT_MAX_ENTRIES = 100_000
DEFAULT_MAX_BYTES = 100 * 1024 * 1024


class SqliteAccessLogStore:
    """Append-oriented SQLite store for sanitized access-log entries."""

    def __init__(
        self,
        path: str | Path,
        *,
        max_entries: int | None = None,
        max_bytes: int | None = None,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.max_entries = max_entries if max_entries is not None else _env_int(
            "EPICORACLE_HTTP_LOG_MAX_ENTRIES", DEFAULT_MAX_ENTRIES
        )
        self.max_bytes = max_bytes if max_bytes is not None else _env_int(
            "EPICORACLE_HTTP_LOG_MAX_BYTES", DEFAULT_MAX_BYTES
        )
        self._lock = threading.Lock()
        self._init_db()

    def write_event(self, event: HttpEvent) -> None:
        """Persist an ``http.request.*`` event payload as an access-log row."""
        if not event.name.startswith("http.request."):
            return
        self.write_entry(AccessLogEntry.model_validate(event.payload))

    def write_entry(self, entry: AccessLogEntry) -> None:
        """Append one access-log row and enforce retention caps."""
        with self._connect() as conn, self._lock:
            conn.execute(
                """
                INSERT INTO access_log (
                    correlation_id, timestamp_utc, principal, method, route_template,
                    status, duration_ms, response_size_bytes, tenant, client_ip, sensitivity
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.correlation_id,
                    _dt_to_db(entry.timestamp_utc),
                    entry.principal,
                    entry.method,
                    entry.route_template,
                    entry.status,
                    entry.duration_ms,
                    entry.response_size_bytes,
                    entry.tenant,
                    entry.client_ip,
                    str(entry.sensitivity.value),
                ),
            )
            self._enforce_retention(conn)

    def query(
        self,
        *,
        tenant: str,
        principal: str | None = None,
        route_template: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        status_min: int | None = None,
        status_max: int | None = None,
        cursor: str | None = None,
        page_size: int = 50,
    ) -> AccessLogPage:
        """Return a tenant-scoped page, ordered newest-first."""
        where, params = self._filters(
            tenant=tenant,
            principal=principal,
            route_template=route_template,
            since=since,
            until=until,
            status_min=status_min,
            status_max=status_max,
        )
        if cursor:
            cursor_ts, cursor_id = _decode_cursor(cursor)
            where.append("(timestamp_utc < ? OR (timestamp_utc = ? AND correlation_id < ?))")
            params.extend([cursor_ts, cursor_ts, cursor_id])

        limit = max(1, page_size)
        with self._connect() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM access_log WHERE {' AND '.join(where)}",
                params,
            ).fetchone()[0]
            rows = conn.execute(
                f"""
                SELECT correlation_id, timestamp_utc, principal, method, route_template,
                       status, duration_ms, response_size_bytes, tenant, client_ip, sensitivity
                FROM access_log
                WHERE {' AND '.join(where)}
                ORDER BY timestamp_utc DESC, correlation_id DESC
                LIMIT ?
                """,
                [*params, limit + 1],
            ).fetchall()

        entries = [_entry_from_row(row) for row in rows[:limit]]
        next_cursor = None
        if len(rows) > limit and entries:
            last = entries[-1]
            next_cursor = _encode_cursor(_dt_to_db(last.timestamp_utc), last.correlation_id)
        return AccessLogPage(entries=entries, next_cursor=next_cursor, total_count=total)

    def count(
        self,
        *,
        tenant: str,
        principal: str | None = None,
        route_template: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        status_min: int | None = None,
        status_max: int | None = None,
    ) -> int:
        where, params = self._filters(
            tenant=tenant,
            principal=principal,
            route_template=route_template,
            since=since,
            until=until,
            status_min=status_min,
            status_max=status_max,
        )
        with self._connect() as conn:
            return int(
                conn.execute(f"SELECT COUNT(*) FROM access_log WHERE {' AND '.join(where)}", params)
                .fetchone()[0]
            )

    def summary(
        self,
        *,
        tenant: str,
        since: datetime | None = None,
        until: datetime | None = None,
        dropped_events_counter: int = 0,
    ) -> AccessLogSummary:
        window_to = until or datetime.now(UTC)
        window_from = since or window_to - timedelta(hours=24)
        where, params = self._filters(tenant=tenant, since=window_from, until=window_to)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT principal, route_template, timestamp_utc, duration_ms
                FROM access_log
                WHERE {' AND '.join(where)}
                """,
                params,
            ).fetchall()

        principals = {row[0] for row in rows if row[0]}
        visits_per_route: dict[str, int] = defaultdict(int)
        last_visit_per_principal: dict[str, datetime] = {}
        latencies: dict[str, list[int]] = defaultdict(list)
        for principal, route, timestamp_raw, duration in rows:
            timestamp = _dt_from_db(timestamp_raw)
            visits_per_route[route] += 1
            latencies[route].append(int(duration))
            if principal and (
                principal not in last_visit_per_principal
                or timestamp > last_visit_per_principal[principal]
            ):
                last_visit_per_principal[principal] = timestamp

        return AccessLogSummary(
            unique_principals=len(principals),
            visits_per_route=dict(visits_per_route),
            last_visit_per_principal=last_visit_per_principal,
            p50_latency_per_route_ms=_percentiles(latencies, 0.50),
            p95_latency_per_route_ms=_percentiles(latencies, 0.95),
            p99_latency_per_route_ms=_percentiles(latencies, 0.99),
            dropped_events_counter=dropped_events_counter,
            window_from=window_from,
            window_to=window_to,
        )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS access_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    correlation_id TEXT NOT NULL,
                    timestamp_utc TEXT NOT NULL,
                    principal TEXT,
                    method TEXT NOT NULL,
                    route_template TEXT NOT NULL,
                    status INTEGER NOT NULL,
                    duration_ms INTEGER NOT NULL,
                    response_size_bytes INTEGER,
                    tenant TEXT NOT NULL,
                    client_ip TEXT,
                    sensitivity TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_access_log_timestamp
                ON access_log(timestamp_utc)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_access_log_principal
                ON access_log(principal)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_access_log_route_template
                ON access_log(route_template)
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_access_log_tenant ON access_log(tenant)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_access_log_status ON access_log(status)")
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_access_log_cursor
                ON access_log(timestamp_utc, correlation_id)
                """
            )

    def _filters(self, *, tenant: str, **filters: Any) -> tuple[list[str], list[Any]]:
        where = ["tenant = ?"]
        params: list[Any] = [tenant]
        if filters.get("principal"):
            where.append("principal = ?")
            params.append(filters["principal"])
        if filters.get("route_template"):
            where.append("route_template = ?")
            params.append(filters["route_template"])
        if filters.get("since"):
            where.append("timestamp_utc >= ?")
            params.append(_dt_to_db(filters["since"]))
        if filters.get("until"):
            where.append("timestamp_utc <= ?")
            params.append(_dt_to_db(filters["until"]))
        if filters.get("status_min") is not None:
            where.append("status >= ?")
            params.append(filters["status_min"])
        if filters.get("status_max") is not None:
            where.append("status <= ?")
            params.append(filters["status_max"])
        return where, params

    def _enforce_retention(self, conn: sqlite3.Connection) -> None:
        if self.max_entries > 0:
            count = int(conn.execute("SELECT COUNT(*) FROM access_log").fetchone()[0])
            excess = count - self.max_entries
            if excess > 0:
                conn.execute(
                    """
                    DELETE FROM access_log
                    WHERE id IN (
                        SELECT id FROM access_log ORDER BY timestamp_utc ASC, id ASC LIMIT ?
                    )
                    """,
                    (excess,),
                )
        if self.max_bytes > 0 and _sqlite_bytes(self.path) > self.max_bytes:
            while _sqlite_bytes(self.path) > self.max_bytes:
                deleted = conn.execute(
                    """
                    DELETE FROM access_log
                    WHERE id IN (
                        SELECT id FROM access_log ORDER BY timestamp_utc ASC, id ASC LIMIT 100
                    )
                    """
                ).rowcount
                if deleted == 0:
                    break
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _dt_to_db(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _dt_from_db(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _entry_from_row(row: sqlite3.Row) -> AccessLogEntry:
    return AccessLogEntry(
        correlation_id=row["correlation_id"],
        timestamp_utc=_dt_from_db(row["timestamp_utc"]),
        principal=row["principal"],
        method=row["method"],
        route_template=row["route_template"],
        status=row["status"],
        duration_ms=row["duration_ms"],
        response_size_bytes=row["response_size_bytes"],
        tenant=row["tenant"],
        client_ip=row["client_ip"],
        sensitivity=row["sensitivity"],
    )


def _encode_cursor(timestamp_utc: str, correlation_id: str) -> str:
    raw = json.dumps({"t": timestamp_utc, "c": correlation_id}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[str, str]:
    raw = base64.urlsafe_b64decode(cursor.encode()).decode()
    parsed = json.loads(raw)
    return str(parsed["t"]), str(parsed["c"])


def _percentiles(latencies: dict[str, list[int]], percentile: float) -> dict[str, float]:
    return {route: _percentile(values, percentile) for route, values in latencies.items()}


def _percentile(values: Iterable[int], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return float(ordered[0])
    if percentile == 0.50:
        return float(quantiles(ordered, n=2, method="inclusive")[0])
    index = round((len(ordered) - 1) * percentile)
    return float(ordered[index])


def _sqlite_bytes(path: Path) -> int:
    files = (path, path.with_suffix(path.suffix + "-wal"))
    return sum(p.stat().st_size for p in files if p.exists())
