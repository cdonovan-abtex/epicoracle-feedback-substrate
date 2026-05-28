"""Pure ASGI HTTP access-log middleware."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from epicoracle_feedback.http_events import emit_http_event
from epicoracle_feedback.schemas.observability import AccessLogEntry, HttpEvent

logger = logging.getLogger(__name__)

Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]
ASGIApp = Callable[[dict[str, Any], Receive, Send], Awaitable[None]]

REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9-]{1,64}$")
DEFAULT_EXCLUDED_CONTENT_TYPES = (
    "image/",
    "text/css",
    "application/javascript",
    "text/javascript",
    "font/",
)


class Counter:
    """Small in-process counter with Prometheus-style access."""

    def __init__(self) -> None:
        self._value = 0
        self._lock = asyncio.Lock()

    @property
    def value(self) -> int:
        return self._value

    async def increment(self) -> None:
        async with self._lock:
            self._value += 1

    def reset(self) -> None:
        self._value = 0


dropped_events_counter = Counter()
sink_failure_counter = Counter()


class HttpLoggingMiddleware:
    """Capture sanitized request telemetry without doing I/O on the hot path."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        enabled: bool = True,
        queue_size: int | None = None,
        tenant: str | None = None,
        excluded_content_types: tuple[str, ...] = DEFAULT_EXCLUDED_CONTENT_TYPES,
    ) -> None:
        self.app = app
        self.enabled = enabled
        self.tenant = tenant or os.environ.get("EPICORACLE_TENANT", "pilot")
        self.excluded_content_types = excluded_content_types
        self.queue: asyncio.Queue[HttpEvent | None] = asyncio.Queue(
            maxsize=queue_size or _env_int("EPICORACLE_HTTP_LOG_QUEUE_SIZE", 10_000)
        )
        self._drain_task: asyncio.Task[None] | None = None

    async def __call__(self, scope: dict[str, Any], receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self._run_lifespan(scope, receive, send)
            return
        if scope["type"] != "http" or not self.enabled:
            await self.app(scope, receive, send)
            return
        await self._call_http(scope, receive, send)

    async def _run_lifespan(self, scope: dict[str, Any], receive: Receive, send: Send) -> None:
        if self.enabled:
            self._ensure_drain_task()
        try:
            await self.app(scope, receive, send)
        finally:
            if self._drain_task is not None:
                await self.queue.put(None)
                await self._drain_task
                self._drain_task = None

    async def _call_http(self, scope: dict[str, Any], receive: Receive, send: Send) -> None:
        started = time.perf_counter()
        timestamp = datetime.now(UTC)
        status = 500
        response_size: int | None = None
        content_type = ""

        async def send_wrapper(message: dict[str, Any]) -> None:
            nonlocal status, response_size, content_type
            if message["type"] == "http.response.start":
                status = int(message["status"])
                headers = {
                    key.decode("latin1").lower(): value.decode("latin1")
                    for key, value in message.get("headers", [])
                }
                content_type = headers.get("content-type", "")
                if headers.get("content-length"):
                    try:
                        response_size = int(headers["content-length"])
                    except ValueError:
                        response_size = None
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            await self._enqueue(scope, timestamp, started, status, response_size, errored=True)
            raise
        if _excluded_content_type(content_type, self.excluded_content_types):
            return
        await self._enqueue(scope, timestamp, started, status, response_size, errored=False)

    async def _enqueue(
        self,
        scope: dict[str, Any],
        timestamp: datetime,
        started: float,
        status: int,
        response_size: int | None,
        *,
        errored: bool,
    ) -> None:
        try:
            self._ensure_drain_task()
            entry = AccessLogEntry(
                correlation_id=_correlation_id(scope),
                timestamp_utc=timestamp,
                principal=_principal(scope),
                method=scope["method"],
                route_template=_route_template(scope),
                status=status,
                duration_ms=max(0, round((time.perf_counter() - started) * 1000)),
                response_size_bytes=response_size,
                tenant=self.tenant,
                client_ip=_client_ip(scope),
            )
            event = HttpEvent(
                name="http.request.errored" if errored else "http.request.completed",
                correlation_id=entry.correlation_id,
                timestamp_utc=entry.timestamp_utc,
                payload=entry.model_dump(mode="json"),
            )
            self.queue.put_nowait(event)
        except asyncio.QueueFull:
            await dropped_events_counter.increment()
            logger.warning("epicoracle_feedback: HTTP access-log queue full; dropping event")
        except Exception:
            await sink_failure_counter.increment()
            logger.warning(
                "epicoracle_feedback: failed to enqueue HTTP access-log event",
                exc_info=True,
            )

    async def _drain_queue(self) -> None:
        while True:
            event = await self.queue.get()
            try:
                if event is None:
                    return
                emit_http_event(event)
            except Exception:
                await sink_failure_counter.increment()
                logger.warning(
                    "epicoracle_feedback: failed to drain HTTP access-log event",
                    exc_info=True,
                )
            finally:
                self.queue.task_done()

    def _ensure_drain_task(self) -> None:
        if self._drain_task is None or self._drain_task.done():
            self._drain_task = asyncio.create_task(self._drain_queue())


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _correlation_id(scope: dict[str, Any]) -> str:
    headers = _headers(scope)
    candidate = headers.get("x-request-id", "")
    if REQUEST_ID_RE.fullmatch(candidate):
        return candidate
    return str(uuid.uuid4())


def _principal(scope: dict[str, Any]) -> str | None:
    headers = _headers(scope)
    stub = headers.get("x-entra-stub-user", "").strip()
    if stub:
        return stub.split(":", 1)[0]
    user = scope.get("user")
    if user is not None:
        return getattr(user, "email", None) or getattr(user, "user_email", None) or str(user)
    return None


def _route_template(scope: dict[str, Any]) -> str:
    route = scope.get("route")
    path = getattr(route, "path", None)
    if path:
        return str(path)
    return str(scope.get("path", "/"))


def _client_ip(scope: dict[str, Any]) -> str | None:
    client = scope.get("client")
    if not client:
        return None
    return str(client[0])


def _headers(scope: dict[str, Any]) -> dict[str, str]:
    return {
        key.decode("latin1").lower(): value.decode("latin1")
        for key, value in scope.get("headers", [])
    }


def _excluded_content_type(content_type: str, prefixes: tuple[str, ...]) -> bool:
    normalized = content_type.split(";", 1)[0].strip().lower()
    return any(normalized.startswith(prefix) for prefix in prefixes)
