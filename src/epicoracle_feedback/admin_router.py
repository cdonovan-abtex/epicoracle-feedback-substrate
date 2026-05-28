"""Admin access-log router factory."""

from __future__ import annotations

import inspect
import ipaddress
import os
import time
from collections import defaultdict, deque
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from epicoracle_feedback.access_log_store import SqliteAccessLogStore
from epicoracle_feedback.events import FeedbackEvent, emit_feedback_event
from epicoracle_feedback.http_middleware import dropped_events_counter

RoleGate = Callable[[Request], Any] | Callable[[], Any]
RateLimiter = Callable[[str], bool]
AuditEmitter = Callable[[FeedbackEvent], None]

TAILNET = ipaddress.ip_network("100.64.0.0/10")
LOCALHOSTS = {
    ipaddress.ip_address("127.0.0.1"),
    ipaddress.ip_address("::1"),
}


class InMemoryRateLimiter:
    """Per-principal fixed-window-ish limiter for admin reads."""

    def __init__(self, limit: int = 60, window_seconds: int = 60) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def __call__(self, principal: str) -> bool:
        now = time.monotonic()
        hits = self._hits[principal]
        while hits and now - hits[0] >= self.window_seconds:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        return True


def build_access_log_router(
    store: SqliteAccessLogStore,
    *,
    role_gate: RoleGate,
    rate_limiter: RateLimiter | None = None,
    audit_emitter: AuditEmitter | None = None,
    max_page_size: int | None = None,
) -> APIRouter:
    """Build the fail-closed access-log admin router."""
    if role_gate is None:
        raise ValueError("role_gate is required")
    limiter = rate_limiter or InMemoryRateLimiter()
    emit_audit = audit_emitter or emit_feedback_event
    page_cap = min(max_page_size or _env_int("EPICORACLE_HTTP_LOG_MAX_PAGE_SIZE", 50), 200)
    router = APIRouter(prefix="/admin/access-log", tags=["admin-access-log"])

    async def require_admin(request: Request) -> Any:
        if not _is_localhost_or_tailnet(_request_ip(request)):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin route is tailnet-only",
            )
        principal = await _call_role_gate(role_gate, request)
        if principal is None:
            principal = _dev_stub_principal(request)
        if principal is None or not _has_admin_role(principal):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
        principal_id = _principal_id(principal)
        if not limiter(principal_id):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded",
            )
        request.state.access_log_principal = principal
        return principal

    @router.get("")
    async def read_access_log(
        request: Request,
        principal_ctx: Any = Depends(require_admin),  # noqa: B008
        principal: str | None = None,
        route_template: str | None = None,
        since: datetime | None = Query(default=None),  # noqa: B008
        until: datetime | None = Query(default=None),  # noqa: B008
        status_min: int | None = Query(default=None, ge=100, le=599),  # noqa: B008
        status_max: int | None = Query(default=None, ge=100, le=599),  # noqa: B008
        tenant: str | None = None,
        cursor: str | None = None,
        page_size: int = Query(default=50, ge=1),  # noqa: B008
    ) -> Any:
        scoped_tenant = _tenant(principal_ctx)
        if tenant is not None and tenant != scoped_tenant:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant scope denied")
        window_to = _utc(until) or datetime.now(UTC)
        window_from = _utc(since) or window_to - timedelta(hours=24)
        _audit(emit_audit, request, principal_ctx, "list")
        return store.query(
            tenant=scoped_tenant,
            principal=principal,
            route_template=route_template,
            since=window_from,
            until=window_to,
            status_min=status_min,
            status_max=status_max,
            cursor=cursor,
            page_size=min(page_size, page_cap),
        )

    @router.get("/summary")
    async def read_access_log_summary(
        request: Request,
        principal_ctx: Any = Depends(require_admin),  # noqa: B008
        since: datetime | None = Query(default=None),  # noqa: B008
        until: datetime | None = Query(default=None),  # noqa: B008
        tenant: str | None = None,
    ) -> Any:
        scoped_tenant = _tenant(principal_ctx)
        if tenant is not None and tenant != scoped_tenant:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant scope denied")
        window_to = _utc(until) or datetime.now(UTC)
        window_from = _utc(since) or window_to - timedelta(hours=24)
        _audit(emit_audit, request, principal_ctx, "summary")
        return store.summary(
            tenant=scoped_tenant,
            since=window_from,
            until=window_to,
            dropped_events_counter=dropped_events_counter.value,
        )

    return router


async def _call_role_gate(role_gate: RoleGate, request: Request) -> Any:
    try:
        sig = inspect.signature(role_gate)
        result = cast(Any, role_gate)(request) if sig.parameters else cast(Any, role_gate)()
    except HTTPException:
        raise
    except Exception:
        result = None
    if inspect.isawaitable(result):
        return await result
    return result


def _dev_stub_principal(request: Request) -> dict[str, Any] | None:
    if os.environ.get("EPICORACLE_DEV_MODE", "").lower() != "true":
        return None
    if not _is_localhost_or_tailnet(_request_ip(request)):
        return None
    raw = request.headers.get("X-Entra-Stub-User", "").strip()
    if not raw or "@" not in raw:
        return None
    email, _, roles_raw = raw.partition(":")
    roles = [role.strip().lower() for role in roles_raw.split(",") if role.strip()]
    if not roles:
        roles = ["admin"]
    return {
        "email": email,
        "roles": tuple(roles),
        "tenant": os.environ.get("EPICORACLE_TENANT", "pilot"),
    }


def _has_admin_role(principal: Any) -> bool:
    if hasattr(principal, "has_any_role"):
        return bool(principal.has_any_role("admin", "admin_full"))
    roles = getattr(principal, "roles", None)
    if roles is None and isinstance(principal, dict):
        roles = principal.get("roles", ())
    if roles is None:
        return False
    return "admin" in roles or "admin_full" in roles


def _tenant(principal: Any) -> str:
    if isinstance(principal, dict):
        return str(principal.get("tenant") or os.environ.get("EPICORACLE_TENANT", "pilot"))
    return str(getattr(principal, "tenant", None) or os.environ.get("EPICORACLE_TENANT", "pilot"))


def _principal_id(principal: Any) -> str:
    if isinstance(principal, dict):
        return str(principal.get("email") or principal.get("user_id") or "unknown")
    return str(
        getattr(principal, "email", None)
        or getattr(principal, "user_email", None)
        or getattr(principal, "user_id", None)
        or "unknown"
    )


def _request_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    if forwarded:
        return forwarded
    if request.client:
        return request.client.host
    return None


def _is_localhost_or_tailnet(ip_raw: str | None) -> bool:
    if not ip_raw:
        return False
    try:
        ip = ipaddress.ip_address(ip_raw)
    except ValueError:
        return False
    return ip in LOCALHOSTS or ip in TAILNET


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="datetime must be UTC",
        )
    return value.astimezone(UTC)


def _audit(emit_audit: AuditEmitter, request: Request, principal: Any, view: str) -> None:
    emit_audit(
        FeedbackEvent(
            name="admin.access_log.read",
            correlation_id=request.headers.get("X-Request-ID", "admin-access-log-read")[:64],
            payload={
                "principal": _principal_id(principal),
                "tenant": _tenant(principal),
                "view": view,
                "path": request.url.path,
            },
        )
    )


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default
