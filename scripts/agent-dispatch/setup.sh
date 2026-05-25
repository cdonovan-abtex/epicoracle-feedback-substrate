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
#
# Strategy: create a dedicated venv at .agent-dispatch-venv/ so we don't
# fight Ubuntu's PEP 668 externally-managed Python protection AND don't
# depend on the earlier `uv sync` having created a venv (which only runs
# if a satellite pyproject.toml is at repo root — not guaranteed for hub).
#
# After install, prepend the venv's bin to GITHUB_PATH so subsequent
# workflow steps (triage.py, dispatch.py, answer_draft.py, etc.) resolve
# `python` to the venv's Python with anthropic + openai + google-generativeai
# already importable.
DISPATCH_REQS=".substrate/scripts/agent-dispatch/requirements.txt"
DISPATCH_VENV="$(pwd)/.agent-dispatch-venv"
if [[ -f "${DISPATCH_REQS}" ]]; then
    if [[ ! -d "${DISPATCH_VENV}" ]]; then
        log "Creating dispatch venv at ${DISPATCH_VENV}"
        uv venv "${DISPATCH_VENV}" --python "${PYTHON_VERSION}"
    fi
    log "Installing agent-dispatch deps from ${DISPATCH_REQS} into ${DISPATCH_VENV}"
    VIRTUAL_ENV="${DISPATCH_VENV}" uv pip install -r "${DISPATCH_REQS}"
    # Make the venv's binaries visible to subsequent workflow steps
    # (GITHUB_PATH is the canonical mechanism for cross-step PATH propagation)
    if [[ -n "${GITHUB_PATH:-}" ]]; then
        echo "${DISPATCH_VENV}/bin" >> "${GITHUB_PATH}"
        log "Added ${DISPATCH_VENV}/bin to GITHUB_PATH"
    else
        log "GITHUB_PATH not set (not running in Actions?) — skipping PATH propagation"
        export PATH="${DISPATCH_VENV}/bin:${PATH}"
    fi
fi

log "Setup complete."
