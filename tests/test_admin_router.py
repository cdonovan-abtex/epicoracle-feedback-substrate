from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from epicoracle_feedback.access_log_store import SqliteAccessLogStore
from epicoracle_feedback.admin_router import build_access_log_router
from epicoracle_feedback.schemas.observability import AccessLogEntry


@dataclass(frozen=True)
class Principal:
    email: str = "admin@example.test"
    tenant: str = "pilot"
    roles: tuple[str, ...] = ("admin",)

    def has_any_role(self, *roles: str) -> bool:
        return any(role in self.roles for role in roles)


def _app(store: SqliteAccessLogStore, principal: Principal | None) -> FastAPI:
    app = FastAPI()

    def role_gate() -> Principal | None:
        return principal

    app.include_router(build_access_log_router(store, role_gate=role_gate))
    return app


def _entry(tenant: str) -> AccessLogEntry:
    # Use a relative timestamp inside the summary endpoint's default 24h
    # lookback window so the test stays green over time. A hardcoded date
    # rots out of the window within a day.
    return AccessLogEntry(
        correlation_id=f"corr-{tenant}",
        timestamp_utc=datetime.now(UTC) - timedelta(minutes=5),
        principal="operator@example.test",
        method="GET",
        route_template="/health",
        status=200,
        duration_ms=3,
        response_size_bytes=None,
        tenant=tenant,
        client_ip="100.64.0.2",
    )


def test_admin_auth_denied_without_valid_admin(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("EPICORACLE_DEV_MODE", raising=False)
    store = SqliteAccessLogStore(tmp_path / "access_log.sqlite")
    with TestClient(_app(store, None)) as client:
        response = client.get(
            "/admin/access-log/summary",
            headers={
                "X-Entra-Stub-User": "admin@example.test:admin",
                "X-Forwarded-For": "100.64.0.2",
            },
        )

    assert response.status_code == 403


def test_admin_non_tailnet_origin_denied(tmp_path) -> None:
    store = SqliteAccessLogStore(tmp_path / "access_log.sqlite")
    with TestClient(_app(store, Principal())) as client:
        response = client.get(
            "/admin/access-log/summary",
            headers={"X-Forwarded-For": "203.0.113.9"},
        )

    assert response.status_code == 403


def test_admin_tenant_leakage_denied(tmp_path) -> None:
    store = SqliteAccessLogStore(tmp_path / "access_log.sqlite")
    store.write_entry(_entry("other"))
    with TestClient(_app(store, Principal())) as client:
        response = client.get(
            "/admin/access-log?tenant=other",
            headers={"X-Forwarded-For": "100.64.0.2"},
        )

    assert response.status_code == 403


def test_admin_summary_returns_tenant_scoped_data(tmp_path) -> None:
    store = SqliteAccessLogStore(tmp_path / "access_log.sqlite")
    store.write_entry(_entry("pilot"))
    store.write_entry(_entry("other"))
    with TestClient(_app(store, Principal())) as client:
        response = client.get(
            "/admin/access-log/summary",
            headers={"X-Forwarded-For": "100.64.0.2"},
        )

    assert response.status_code == 200
    assert response.json()["visits_per_route"] == {"/health": 1}
