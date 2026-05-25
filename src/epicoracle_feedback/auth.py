"""GitHub authentication resolution for the dispatcher.

Two postures:

1. **Production** (``GH_TOKEN`` env var present): use the token directly via
   ``gh`` CLI's ``GH_TOKEN`` env handoff. This is 12-factor compliant and
   matches Gemini's BLOCKER on host-gh-auth-state in production.
2. **Dev** (no ``GH_TOKEN``): fall back to whatever the host's ``gh auth``
   has stashed — this is the existing marketplace behaviour and keeps the
   developer loop friction-free on MBP/Mac mini.

The dispatcher never reads ``GH_TOKEN`` itself; it just resolves it once
here and passes the env block into the subprocess. That keeps the token
out of process argv (where it would show up in ``ps``).
"""

from __future__ import annotations

import os

_ENV_VAR = "GH_TOKEN"


def resolve_gh_token(explicit: str | None = None) -> str | None:
    """Return the GH token the dispatcher should use, or None to defer to host gh.

    Precedence:

    1. ``explicit`` argument from the caller (production path; the FastAPI
       app reads its own ``settings.gh_token`` and passes it in).
    2. ``GH_TOKEN`` environment variable (LLT / container deploy path).
    3. ``None`` — caller falls back to host gh CLI auth state (dev path on
       MBP / Mac mini).

    The function never raises. The dispatcher decides what to do with
    ``None`` (typically: still call ``gh``, trust host auth).
    """
    if explicit:
        return explicit
    env_value = os.environ.get(_ENV_VAR, "").strip()
    return env_value or None


def gh_env(token: str | None) -> dict[str, str]:
    """Build the env dict to hand to ``subprocess.run`` for ``gh``.

    When a token is present we inject it ONLY into the subprocess
    environment, not into our own process env (so we don't accidentally
    pollute peer subprocesses launched later). When absent, we hand back
    the parent env unchanged so ``gh`` can read whatever host config it
    knows about.
    """
    env = os.environ.copy()
    if token:
        env[_ENV_VAR] = token
    return env
