#!/usr/bin/env bash
# Agent-dispatch runner setup — version-pinned dependencies.
#
# Invoked as the first step of .github/workflows/agent-dispatch.yml. Installs
# the Python toolchain, Node toolchain, and Playwright headless browser at
# pinned versions so reproducibility across runs is deterministic.
#
# Pinned versions live ONLY here; bumping them is an intentional substrate
# release (CHANGELOG entry + tag) so satellites can verify the bump.

set -euo pipefail

# ---- Pinned versions ------------------------------------------------------

PYTHON_VERSION="3.12.7"
UV_VERSION="0.10.11"
NODE_VERSION="20.18.0"
PLAYWRIGHT_VERSION="1.49.0"

# ---- Echo helper ----------------------------------------------------------

log() { printf '[setup] %s\n' "$*" >&2; }

# ---- Python via uv --------------------------------------------------------

if ! command -v uv >/dev/null 2>&1; then
    log "Installing uv ${UV_VERSION}"
    curl -LsSf "https://astral.sh/uv/${UV_VERSION}/install.sh" | sh
    # shellcheck disable=SC1091
    source "$HOME/.local/bin/env" 2>/dev/null || true
    export PATH="$HOME/.local/bin:$PATH"
fi

log "uv: $(uv --version)"
log "Installing Python ${PYTHON_VERSION}"
uv python install "${PYTHON_VERSION}"

# ---- Node / Playwright ----------------------------------------------------

if ! command -v node >/dev/null 2>&1; then
    log "Node not present on runner — relying on GHA setup-node step in workflow"
fi

if command -v npm >/dev/null 2>&1; then
    log "Installing Playwright ${PLAYWRIGHT_VERSION}"
    npm install -g "playwright@${PLAYWRIGHT_VERSION}"
    npx playwright install chromium --with-deps
fi

# ---- Substrate package ----------------------------------------------------

# The workflow runs from the substrate-using satellite's checkout. The
# satellite's pyproject.toml depends on epicoracle-feedback at a pinned
# git tag; ``uv sync`` resolves it into the worktree's venv.
if [[ -f "pyproject.toml" ]]; then
    log "uv sync in satellite checkout"
    uv sync --frozen 2>/dev/null || uv sync
fi

# ---- Agent-dispatch runtime deps (LLM SDKs) -------------------------------

# These are scoped to the agent-dispatch scripts only — NOT bundled into
# the substrate package consumers install (satellites don't need LLM SDKs
# at runtime; only the CI workflow does).
DISPATCH_REQS=".substrate/scripts/agent-dispatch/requirements.txt"
if [[ -f "${DISPATCH_REQS}" ]]; then
    log "Installing agent-dispatch deps from ${DISPATCH_REQS}"
    uv pip install -r "${DISPATCH_REQS}"
fi

log "Setup complete."
