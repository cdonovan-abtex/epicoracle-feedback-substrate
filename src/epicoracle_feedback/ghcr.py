"""GHCR package-coordinate helpers.

The GHCR migration is deferred, so sandbox pulls and image publishing stay
explicitly disabled by default. When Captain later authorizes activation,
use the current repository basename or an explicit package identity, keep the
package private, authenticate pulls with ``packages: read``, grant exact
repository/package access, and label the source via
``org.opencontainers.image.source``.

This module only validates and constructs coordinates; it does not activate
any workflow or perform any registry access.
"""

from __future__ import annotations

import re
from typing import Final

DEFAULT_GHCR_TAG: Final[str] = "main-latest"
GHCR_SANDBOX_ENABLED_ENV: Final[str] = "GHCR_SANDBOX_ENABLED"
GHCR_PACKAGE_NAME_ENV: Final[str] = "GHCR_PACKAGE_NAME"

_TRUE_VALUES: Final[set[str]] = {"1", "true", "yes", "on"}
_NAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")


def _validate_name(value: str, *, field: str) -> str:
    candidate = value.strip()
    if not candidate:
        raise ValueError(f"{field} is empty")
    if "/" in candidate:
        raise ValueError(f"{field} must not contain '/' characters")
    if not _NAME_RE.fullmatch(candidate):
        raise ValueError(f"{field} is malformed: {candidate!r}")
    return candidate


def _split_repository(repository: str) -> tuple[str, str]:
    candidate = repository.strip()
    if not candidate:
        raise ValueError("GITHUB_REPOSITORY is empty")
    if candidate.count("/") != 1:
        raise ValueError("GITHUB_REPOSITORY must be 'owner/name'")
    owner, repo_name = candidate.split("/", 1)
    return _validate_name(owner, field="repository owner"), _validate_name(
        repo_name, field="repository name"
    )


def resolve_ghcr_image(
    github_repository: str,
    *,
    package_name: str | None = None,
    tag: str = DEFAULT_GHCR_TAG,
) -> str:
    """Build the GHCR image coordinate for a repository.

    The default package identity is the repository basename. An explicit
    package name may be provided for a deliberate future mismatch. The
    repository owner always comes from ``GITHUB_REPOSITORY``.
    """

    owner, repo_name = _split_repository(github_repository)
    package = repo_name if package_name is None else package_name
    return (
        f"ghcr.io/{owner}/{_validate_name(package, field='package name')}"
        f":{_validate_name(tag, field='tag')}"
    )


def sandbox_pull_enabled(flag: str | None) -> bool:
    """Return ``True`` only when the deferred GHCR sandbox has been opted in."""

    return bool(flag and flag.strip().lower() in _TRUE_VALUES)
