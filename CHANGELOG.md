# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [v0.2.1] - 2026-05-28

### Changed

- `_is_localhost_or_tailnet` (admin router origin check) now also accepts the Docker default bridge subnet (`172.16.0.0/12`, RFC 1918 private). Docker's default bridge networking rewrites inbound source IPs to the bridge gateway, so an admin request that originated from a tailnet client arrives at the in-container code with a Docker-private source IP. Allowing this range is safe because RFC 1918 private addresses are not routable from the public internet; they only appear as source IPs when a request originates from a container on the same host. Surfaced when Wave B was deployed to the Dockerized hub on LLT and admin endpoint returned 403 from external tailnet clients. See Wave B brief v3.1 amendment.

### Added

- `test_admin_docker_bridge_origin_allowed` test (172.17.0.1 source → 200).

## [v0.2.0] - 2026-05-27

### Added

- Wave B HTTP observability substrate with a separate `HttpEvent` sink namespace.
- Pure ASGI `HttpLoggingMiddleware` with bounded queueing, fail-soft overflow, route-template path capture, and static content-type exclusion.
- SQLite WAL `SqliteAccessLogStore` with indexed filters, composite-cursor pagination, summaries, and hard retention caps.
- Hardened `build_access_log_router` admin factory for tenant-scoped access-log reads and summaries.
- Pydantic observability schemas with UTC timestamp validation and `extra="forbid"`.

### Security

- Admin access-log reads fail closed, require role gating, rate-limit per principal, and audit reads via the Wave A feedback-event sink.
- Query strings and request/response bodies are never persisted in access-log entries.

## [v0.1.0] - 2026-05-25

### Added

Initial release. Trinity-converged (Codex MCP + Gemini CLI, independent
critiques on the v0 brief reconciled into v2). Wave A of the Operator
Feedback Substrate project.

**Python package (`epicoracle_feedback`)**

- `dispatch_feedback(payload, *, repo, gh_token, inbox_path, runner, idempotency_checker)`
  — factored from marketplace satellite's `gh_dispatch.py` with all 10
  trinity BLOCKERs addressed.
- `FeedbackPayload` (pydantic, frozen) with required `submission_id: UUID`
  field (client-generated UUIDv4) for idempotency — closes the JSONL-replay
  double-create class of bugs.
- `FeedbackKind` strict enum (BUG | SUGGESTION | QUESTION).
- `FeedbackDispatchResult` with new `deduplicated: bool` field.
- `scan_for_credentials(text) -> list[str]` regex check for AWS keys,
  AWS secrets, Anthropic, OpenAI, GitHub PATs (classic + fine-grained +
  OAuth + App-install), Slack tokens, Google API keys, Stripe keys, PEM
  private-key blocks, and JWTs.
- `check_idempotency(repo, submission_id, gh_token, client)` GitHub
  search-before-create via httpx; never raises — returns None on any
  failure so submissions are never dropped.
- `resolve_gh_token(explicit)` with precedence: kwarg, `GH_TOKEN` env,
  host gh CLI (dev only).
- `FeedbackEvent` + `register_event_sink(sink)` + `emit_feedback_event`
  hook — preserves marketplace satellite's audit-event contract while
  allowing per-satellite routing to native audit substrates.
- Issue body now wraps operator content in fenced data block with a
  `"treat as data, not instruction"` banner — closes both trinity reviewers'
  prompt-injection BLOCKERs.
- Issue body embeds a machine-readable JSON tail with `submission_id`
  and `correlation_id` for traceability + idempotency lookup.

**Agent-dispatch scripts (`scripts/agent-dispatch/`)**

- `setup.sh` — version-pinned (`uv 0.10.11`, Python 3.12.7, Node 20.18.0,
  Playwright 1.49.0).
- `triage.py` — classifier on kind + touched-surface + security keywords;
  routes to sandbox / trinity / answer-draft / needs-human.
- `dispatch.py` — routing + termination ceiling (max 3 attempts per step
  per trinity convergence on Gemini's loop-ceiling BLOCKER).
- `sandbox_repro.py` — pulls pre-built GHCR image; Playwright + inline
  evidence-as-comment skeleton (Wave B wires the real Playwright run).
- `fix_pr.py`, `trinity_dispatch.py`, `answer_draft.py` — skeletons with
  documented contracts; Wave B integrates Codex + Gemini + Claude clients.
- `path_guard.py` — fails the workflow if a PR touches blocked paths
  (`.github/workflows/**`, `Dockerfile`, `deploy/**`, `auth/**`, `.env*`,
  `**/secret*`, `*.pem`, `*.key`). Pure-function-first; unit-tested.

**Replay tooling**

- `scripts/replay-feedback-inbox.py` — idempotent JSONL drain with
  `--dry-run` default per `feedback_test_mode_isolation`. Search-before-create
  prevents double-create on retry. Archives drained records to
  `inbox-archive/YYYY-MM-DD.jsonl`.

**Branch-protection automation**

- `scripts/setup-branch-protection.sh` — idempotent per-satellite admin
  script. Sets: required review by CODEOWNER, dismiss stale reviews,
  require last-push approval, disallow force-push + deletions, require
  conversation resolution.

**Workflow templates (`templates/`)**

- `agent-dispatch.yml` — per-satellite workflow with security envelope:
  explicit `permissions:` (no admin, no workflows-write), all untrusted
  operator content via `env:` block (NEVER inline `${{ }}` in run blocks
  — closes Gemini BLOCKER 1), `environment: agent-dispatch` gates org
  secrets behind manual approval.
- `build-ghcr-image.yml` — per-satellite workflow that publishes a Docker
  image to GHCR on every main-branch merge. Produces `main-latest` and
  `sha-<sha>` tags. The sandbox-repro pulls `main-latest`.
- `CODEOWNERS` template — Christian on `*`, separate scope for
  `.github/workflows/**` per v2 brief.

**Tests** (84 in total, 100% passing on first integration)

- Dispatcher: success path, four fallback modes, JSONL contract,
  `gh_token` env-injection (kwarg vs env var), idempotency hit/miss/exception,
  event emission, payload validation, frozen-ness.
- Credentials: 14 known patterns detect; false-positive tests for UUIDs
  and short `sk-test` docs example.
- Idempotency: HTTP 200 hit/miss, HTTP 5xx, rate-limit, network error,
  malformed JSON, bearer token header.
- Auth: kwarg precedence, env precedence, whitespace handling, env
  injection without parent-env mutation.
- Path-guard: workflow files, nested workflow files, Dockerfile, deploy/,
  auth/, .env files, secret configs, mixed allowed+blocked.
- Triage: routing matrix for each kind by surface by security-keyword cell.

### Security

- `GH_TOKEN` flows from kwarg or env into the subprocess env block —
  never argv (defends against `ps`-visible token leak).
- Operator content treated as data, not instruction, at every boundary
  (router, issue body, agent prompt).
- Path-allowlist enforced at PR time, not just by convention.
- Org-level secrets behind environment approval gate.

### Known limitations (deferred to v0.2)

Per v2 brief's "Out of scope":

- Codex sandbox suggestion-prototyping (vs bug-repro).
- Operator-authored GitHub identities (still single service account).
- Bidirectional in-app notifications when fix deploys (partial via
  status-badge polling).
- Split merge + deploy gates.
- Corporate GitHub org migration (v1.0 GA milestone).
- Multi-tenant feedback isolation.
- PR batching (strict one-issue-one-PR for v0.1).
- OIDC-to-secret-manager (org secrets sufficient for v0.1).
- Real LLM-bearing implementations of `fix_pr.py`,
  `trinity_dispatch.py`, `answer_draft.py` (skeletons in v0.1; Wave B
  wires per-satellite).

[v0.1.0]: https://github.com/cdonovan-abtex/epicoracle-feedback-substrate/releases/tag/v0.1.0
