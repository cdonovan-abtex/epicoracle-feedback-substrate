"""Wave B HTTP observability schemas."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SensitivityClass(StrEnum):
    """Sensitivity tier for access-log entries."""

    LOW = "low"
    MEDIUM = "medium"
    INTERNAL = "internal"
    HIGH = "high"
    CRITICAL = "critical"


def _must_be_utc(v: datetime) -> datetime:
    offset = v.utcoffset()
    if v.tzinfo is None or offset is None or offset.total_seconds() != 0:
        raise ValueError("timestamp_utc must be timezone-aware UTC")
    return v


class HttpEvent(BaseModel):
    """One HTTP-domain observability event."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: Literal["http.request.completed", "http.request.errored", "admin.access_log.read"]
    correlation_id: str = Field(..., min_length=1, max_length=64, pattern=r"^[A-Za-z0-9-]{1,64}$")
    timestamp_utc: datetime
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("timestamp_utc")
    @classmethod
    def timestamp_must_be_utc(cls, v: datetime) -> datetime:
        return _must_be_utc(v)


class AccessLogEntry(BaseModel):
    """One sanitized HTTP request-log row."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    correlation_id: str = Field(..., min_length=1, max_length=64, pattern=r"^[A-Za-z0-9-]{1,64}$")
    timestamp_utc: datetime
    principal: str | None = Field(None, max_length=320)
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]
    route_template: str = Field(..., min_length=1, max_length=512)
    status: int = Field(..., ge=100, le=599)
    duration_ms: int = Field(..., ge=0)
    response_size_bytes: int | None = Field(None, ge=0)
    tenant: str = Field(..., min_length=1, max_length=64)
    client_ip: str | None = Field(None, max_length=64)
    sensitivity: SensitivityClass = SensitivityClass.INTERNAL

    @field_validator("timestamp_utc")
    @classmethod
    def timestamp_must_be_utc(cls, v: datetime) -> datetime:
        return _must_be_utc(v)


class AccessLogPage(BaseModel):
    """Paginated access-log result."""

    model_config = ConfigDict(extra="forbid")

    entries: list[AccessLogEntry]
    next_cursor: str | None
    total_count: int = Field(..., ge=0)


class AccessLogSummary(BaseModel):
    """Aggregated access-log view for admin surfaces."""

    model_config = ConfigDict(extra="forbid")

    unique_principals: int = Field(..., ge=0)
    visits_per_route: dict[str, int]
    last_visit_per_principal: dict[str, datetime]
    p50_latency_per_route_ms: dict[str, float]
    p95_latency_per_route_ms: dict[str, float]
    p99_latency_per_route_ms: dict[str, float]
    dropped_events_counter: int = Field(..., ge=0)
    window_from: datetime
    window_to: datetime

    @field_validator("last_visit_per_principal")
    @classmethod
    def last_visits_must_be_utc(cls, v: dict[str, datetime]) -> dict[str, datetime]:
        for timestamp in v.values():
            _must_be_utc(timestamp)
        return v

    @field_validator("window_from", "window_to")
    @classmethod
    def window_must_be_utc(cls, v: datetime) -> datetime:
        return _must_be_utc(v)
