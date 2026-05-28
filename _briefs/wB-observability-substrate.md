# Wave B — Observability Substrate

**Version**: v3.2 (Phase 10 synthetic-admin gap documented + deferred, 2026-05-28).
**Branch**: `feat/wB-observability-substrate` off `main`.
**Goal**: Add a pure-observability primitive to the EpicOracle Family kit so every satellite can answer "who is hitting this surface, when, with what status" without forensics. Ships HTTP request-log middleware + an SQLite-backed access-log store + a hardened admin endpoint contract. Compliance's in-progress validation-state server-side persistence is **moved out of this wave** per Gemini's separation-of-concerns critique — it ships separately as a compliance-internal feature.

Wave B is the natural extension of Wave A. Wave A shipped `events.py` (`FeedbackEvent` + `register_event_sink` + `emit_feedback_event`) as the observability hook for feedback-domain events. Wave B keeps `events.py` for what it already does and adds a **separate** observability path for HTTP-domain events with its own sink namespace and its own persistence store. The two paths share event-vocabulary discipline but not their sinks — HTTP events are high-volume/low-signal; feedback events are low-volume/high-signal.

---

## Why this wave lands now

The 2026-05-27 working session surfaced a load-bearing operational gap: three satellites (hub, marketplace, compliance) are deployed to LLT via Tailscale Funnel and serving live traffic. Christian sent the compliance URL to John Chesnes (the eventual operator) and inadvertently to Dan Kirtz (COO). Dan visited; whether John has touched it is unknowable today. The investigation that surfaced the gap took ~30 minutes of forensics (nginx config, Tailscale serve status, GitHub issue history, codebase greps) — exactly the kind of question the substrate should answer in 5 seconds.

The cost of NOT shipping it is paid every time the operator needs to answer "is anyone hitting this" and has to do forensics — and more importantly, paid in trust when an operator (John) is given access and we can't tell whether he's engaged or not.

Composes with existing memory:
- [[reference_secrets_storage_pattern]] — observability data is sensitivity-classified per the same model
- [[feedback_kintsugi_visible_repair]] — visible audit trail is the substrate ethos
- [[feedback_per_product_agent_ecosystem]] — observability per satellite, fan-out at sink level
- [[feedback_self_contained_self_healing_canonical_incident]] — observability is one of the diagnostic surfaces a satellite needs
- [[feedback_tag_routed_issue_agent]] — admin-endpoint pattern complements the issue-driven feedback loop
- [[project_compliance_satellite_emerging]] — compliance is the canonical first consumer
- [[feedback_trinity_reconciles_artifacts]] — v2 of this brief was produced by trinity-reconciliation, not opinion-averaging

---

## v1 → v2 reconciliation notes

Trinity-vet ran 2026-05-27 13:00 EDT. Codex MCP critique (implementation-correctness lens) and Gemini CLI critique (architectural-alternatives lens) produced independent structured critiques. Codex recommendation: `requires_rework`. Gemini recommendation: `major_revisions`. Both correct; v2 absorbs both.

### Convergent findings (both reviewers flagged — fixed in v2)

| # | Finding | Codex ref | Gemini ref | v2 resolution |
|---|---|---|---|---|
| C-1 | Async middleware MUST NOT do sync I/O on the hot path | B-2 (high) | N-1 | Middleware enqueues to a bounded `asyncio.Queue`; a background worker drains to SQLite. Middleware work = schema construction + nonblocking enqueue. Specified in Scope §1 and Operational contract. |
| C-2 | JSONL has multi-layer correctness issues (locking, multi-worker, partial writes, growth, query degradation) | B-3 (high), B-6 (medium) | B-2 (medium), flags | **SQLite WAL mode is the single persistence store.** JSONL eliminated entirely. Addresses Codex's locking/partial-write concerns and Gemini's dual-write complexity concern simultaneously. |
| C-3 | Path / query-string / PII leak risk | B-5 (high) | flag (concern) | Middleware MUST normalize path to route template (no raw values), strip query strings by default, configurable redaction allowlist if query capture is enabled. AccessLogEntry.path now stores route templates. |
| C-4 | Storage growth + query degradation | B-6 (medium) | flag (concern) | Hard default retention cap (100k entries OR 100MB per satellite, satellite-configurable). SQLite WAL with indexed columns handles pagination/filter without scan-from-top. |

### Divergent findings — Claude reconciliation calls (per `feedback_trinity_reconciles_artifacts`, preserve attribution)

**D-1: Sink contract** — *Codex (Q1): hybrid (extend Wave A events sink with composition). Gemini (Q1): separate (don't extend Wave A's sink at all).*
- **Call: separate namespace and separate sink registration**. New module `epicoracle_feedback/http_events.py` with its own `HttpEvent`, `register_http_event_sink`, `emit_http_event`. Wave A's `events.py` unchanged.
- **Reasoning**: Gemini's volume/signal argument is correct — HTTP events are high-volume/low-signal while feedback events are low-volume/high-signal. Coupling them via one sink risks blowing out downstream consumers of feedback events. Codex's sink-replacement-race concern (B-1) is fully resolved by the separation — Wave A's sink slot is untouched.

**D-2: Persistence layer** — *Codex (Q2): both (JSONL primary, SQLite mirror, one consistency mode). Gemini (Q2): SQLite-only (WAL mode), YAGNI on JSONL.*
- **Call: SQLite WAL only**.
- **Reasoning**: Gemini's argument is decisive — SQLite WAL provides ACID guarantees, native pagination/filtering/aggregation (which the admin endpoint contract requires), and avoids file-lock blocking issues in async FastAPI. Most of Codex's B-3 concerns are resolved by abandoning JSONL entirely. The "inspect with grep" benefit Codex implicitly valued in JSONL is replaced by an `epicoracle-feedback access-log dump` CLI helper if needed (deferred).

**D-3: Sensitivity class default** — *Codex (Q3): HIGH (operator-internal data with PII risk). Gemini (Q3): INTERNAL (operational telemetry, sanitization handles risk).*
- **Call: INTERNAL with mandatory sanitization built into the schema contract**.
- **Reasoning**: Codex's HIGH was a proxy for "this isn't safe yet"; the actual safety control is sanitization. With route-template paths, stripped query strings, and no-notes-in-progress-store, the residual content is operational telemetry that belongs at INTERNAL. Per-route elevation to HIGH remains configurable for write-surface routes.

**D-4: Admin auth model** — *Codex (Q4): both (`admin_full` + new `audit_viewer` role). Gemini (Q4): reuse `admin_full` (YAGNI).*
- **Call: reuse `admin_full` for the role gate, BUT absorb all of Codex's admin-endpoint hardening (B-4) regardless of which role guards it.**
- **Reasoning**: Gemini's YAGNI argument wins on the role itself — adding `audit_viewer` is reversible if usage pattern emerges. But Codex's B-4 concerns (fail-closed auth, no stub-user outside explicit dev mode, tenant-scoped filtering, max page size, default lookback window, per-principal rate limiting, audited reads) are all valid and absorbed into the admin contract.

**D-5: Validation-progress server-side persistence — SCOPE CUT** — *Codex (Q5): hybrid (substrate owns schemas/helpers, satellite owns persistence). Gemini (B-1, Q5): entirely owned by compliance satellite, OUT of substrate.*
- **Call: validation-progress is moved OUT of Wave B entirely. Wave B is pure HTTP observability.**
- **Reasoning**: Gemini's separation-of-concerns argument is structurally correct — validation progress is application domain state for compliance, not cross-cutting infrastructure. Bundling them couples the substrate to compliance-specific logic and violates the substrate's generic nature. Codex's hybrid would still have the substrate "managing" the schema for a single-consumer domain feature, which is premature abstraction.
- **This is a scope change from Christian's authorized v1 scope (A — single wave including validation-progress). Surfacing for ratification at Phase 4.** Compliance's validation-progress persistence becomes a separate compliance-internal wave (compliance-W3 candidate).

### Unilateral findings — Codex only (absorbed into v2)

- **B-1 sink races** → resolved by D-1 (separate namespace; Wave A sink untouched)
- **B-4 admin endpoint security** → fail-closed auth, tenant-scoped pre-pagination, max page size (50, configurable to 200 max), default lookback window (24h), per-principal rate limit (60 req/min), audited reads — all in Operational contract
- **B-7 admin audit recursion** → admin endpoint emits `admin.access_log.read` event on its OWN namespace (feedback events sink), explicitly NOT into the HTTP-events sink. Single read = single event, no recursion path.
- **B-8 test obligations** → explicit unit + integration test acceptance added to Acceptance criteria
- **N-1 `from` keyword conflict** → renamed to `since` / `until` in query params and Python args (alias to `from`/`to` if API contract requires)
- **N-2 Pydantic field constraints** → all schemas get `Field` constraints + `extra="forbid"`
- **N-3 UTC normalization** → all timestamps `datetime` with `tzinfo=UTC` enforced via validator
- **N-4 `response_size_bytes` unreliable** → spec as `int | None`, derived from `Content-Length` header when present, else None
- **N-5 `BaseHTTPMiddleware` caveats** → switching to pure ASGI middleware pattern (no `BaseHTTPMiddleware` dependency); justification in Scope §1
- **N-6 template inheritance via commented placeholder is fragile** → template ships with middleware **disabled by default** via env var (`EPICORACLE_HTTP_LOG_ENABLED=false`); SATELLITE_CHECKLIST item explicitly says "flip to true after wiring"

### Unilateral findings — Gemini only (absorbed into v2)

- **B-1 domain/infrastructure conflation** → resolved by D-5 (validation-progress moved out)
- **OQ-2 static-asset exclusion fragility** → middleware default excludes by **response Content-Type** (`image/*`, `text/css`, `application/javascript`, etc.) rather than path patterns. Path patterns remain as supplementary configurable override. Framework-agnostic.

### Phase 4 ratifications (Christian, 2026-05-27 13:25 EDT)

All three open questions resolved before dispatch. v2 build dispatched against these decisions.

1. **Scope cut ratified**: validation-progress server-side persistence moves OUT of Wave B. Becomes compliance-W3 candidate if compliance pursues it. Wave B is pure HTTP observability.
2. **Admin gating = tailnet-only** via Tailscale serve config. Rationale from Christian: *"I am the only one that wants to see this ever."* No public Funnel exposure of admin endpoints. Admin router on each satellite is configured to only respond on tailnet-routed requests (100.64.0.0/10 source IP check) until real Entra (W2) replaces this. If Christian moves to a non-tailnet machine, he'll Tailscale to view admin. This is the simplest possible answer given a single-viewer-ever posture.
3. **Retention cap confirmed**: 100k entries OR 100MB per satellite, whichever first. Configurable per-satellite via env vars (`EPICORACLE_HTTP_LOG_MAX_ENTRIES`, `EPICORACLE_HTTP_LOG_MAX_BYTES`).

---

### v2 → v3 amendment notes (Phase 4.5, 2026-05-28)

This amendment closes a gap the v2 brief left silent: **how do satellites reference the substrate as a Python dependency after Wave B ships?** The v2 dispatch prompt filled this gap with "use editable install of the worktree (`pip install -e ~/Developer/wB-worktrees/substrate`)" — an architectural choice introduced post-trinity. The Phase 5 build agent followed that instruction literally and committed `file://` refs to all 4 satellite/template branches, rendering them un-mergeable as-shipped.

Christian named the pattern explicitly: *"Why are you introducing things after trinity? kind of defeats the purpose?"* and authorized a structural fix — the wave-lifecycle now has Phase 4.5 (pre-dispatch convergence) precisely to catch this class of drift before dispatch. See template `WAVE_LIFECYCLE.md` + `feedback_dispatch_prompt_is_mechanical_only` + `feedback_no_unilateral_architectural_decisions` + `feedback_correct_beats_quick`.

The amendment decision (re-trinity'd at Phase 4.5):

**Decision: Substrate dependency reference shape**

Satellites and the template reference the substrate via git-tag URL:

```
"epicoracle-feedback @ git+https://github.com/cdonovan-abtex/epicoracle-feedback-substrate.git@v0.2.0"
```

Rationale:

- **Matches existing template-main convention.** Template main today references the substrate as `git+https://github.com/cdonovan-abtex/epicoracle-feedback-substrate.git@v0.1.0` (Wave A). Wave B is a version bump on the same shape, not a new pattern.
- **Portable to LLT and any other deploy target.** Installs from GitHub, not a Christian-MBP-specific filesystem path. Satellites become deployable from any host with internet access to GitHub.
- **Semantic versioning preserved.** Tag-pinned ref is human-readable and aligns with the substrate's existing v0.1.0 → v0.2.0 progression. No PyPI publishing needed; no PyPI infrastructure to maintain.
- **No new authentication requirements.** Public GitHub repo; no token or deploy key. Anyone with `git+https` install support (uv, pip, poetry) can resolve it.

Affected files (satellite branches that need flipping from `file://` to the git+https form):

- `epicoracle/backend/pyproject.toml` (hub) — `feat/wB-adopt-observability`
- `epicoracle/backend/requirements.txt` (hub)
- `epicoracle-marketplace/backend/pyproject.toml` (marketplace) — `feat/wB-adopt-observability`
- `epicoracle-compliance/backend/pyproject.toml` (compliance) — `feat/wB-adopt-observability`
- `epicoracle-satellite-template/backend/pyproject.toml` (template) — `feat/wB-inherit-observability`

Phase ordering implication: the v0.2.0 git tag must exist on the substrate repo at GitHub BEFORE the satellite branches merge. Otherwise the new dep-ref points at a non-existent tag and `uv sync` fails.

Updated Phase 7+8 sequence for Wave B:

1. Push substrate `feat/wB-observability-substrate` → merge to substrate main → push main
2. Tag substrate main as `v0.2.0` → push tag (Phase 8 — must precede satellite merges)
3. Flip dep-ref in the 4 satellite/template branches from `file://` to `git+https://...@v0.2.0`
4. Verify satellites resolve the new ref (`uv sync` clean) and tests still pass
5. Push satellite/template feat branches → merge to each main

**For waves after Wave B**: Phase 4.5 catches this class of issue before dispatch, not after. Future wave dispatch prompts get vetted as faithful translations of trinity-vetted briefs; brief amendments (with re-trinity if architectural) close gaps that surface during prompt-drafting.

#### v3 trinity-lite reconciliation (Phase 4.5, 2026-05-28)

The amendment was reviewed by Codex MCP (`gpt-5-codex`, implementation-correctness lens) and Gemini CLI (`gemini-3.1-pro-preview`, architectural-alternatives lens). Both verdicts: `minor_revisions`. Reconciliation calls below preserve reviewer attribution per `feedback_trinity_reconciles_artifacts`.

**Convergent findings (both reviewers flagged — adopted):**

1. **Tag protection mandate** *(Codex C-2 + Gemini C-2)* — Git tags can be deleted or moved unless protected at the host level. The `v0.2.0` substrate tag (and all future release tags) must be protected at GitHub via branch/tag protection rules: no force-push, no delete, no rewrite. Satellite lockfiles capture the resolved commit at install time, but the tag identity must remain stable for human auditability and clean dependency resolution.

2. **Lockfile refresh discipline for future waves** *(Codex C-3 + Gemini C-3)* — Each future wave's version bump in adopting satellites must run `uv lock` (or equivalent) and commit the lockfile changes. Otherwise `pyproject.toml` bumps can be masked by stale lockfiles. Adding to future-wave checklist:

   ```
   For each adopting satellite per wave bump:
   1. Verify substrate tag exists at GitHub and is protected
   2. Update epicoracle-feedback dep ref to @vX.Y.Z in pyproject.toml + requirements.txt
   3. Run `uv lock` (or equivalent) to refresh the lockfile
   4. Commit lockfile + dep-ref together
   5. Run satellite test suite
   6. PR + merge
   ```

**Divergent finding — Claude reconciliation call (load-bearing, Gemini-only):**

**Gemini C-1 (HIGH): CI friction for cross-repo development.** Gemini's concern: if satellite PRs run CI that does `uv sync`, but the dep ref is `@v0.2.0` and v0.2.0 hasn't been tagged yet, CI fails during development. The strict tag-before-merge ordering creates a cross-repo CI deadlock. Codex did not flag this; only Gemini caught it.

- **Reconciliation**: the phase ORDERING is correct (Codex right — tag-before-merge is the right sequence for committed state). The WORKFLOW within that ordering needs explicit guidance (Gemini right — dev-time refs need a path that doesn't require the tag to exist yet).

- **Resolution**: dev-time satellite branches MAY temporarily reference the substrate via branch name (`@feat/wB-observability-substrate`) or commit SHA (`@<sha>`) for local development and CI validation. **Before merge to satellite main**, the ref MUST be flipped to the immutable tag (`@v0.2.0`). The pre-merge tag-ref enforcement is the contract; the dev-time ref shape is flexible.

  Practical sequence: (a) substrate work happens on `feat/wB-observability-substrate`, (b) satellite branches use `@feat/wB-observability-substrate` ref during local dev + initial CI validation, (c) substrate merges to main + gets tagged `v0.2.0`, (d) satellite branches flip refs from feat-branch to `@v0.2.0`, (e) re-run CI to validate against the immutable tag, (f) merge satellite branches.

  This avoids the cross-repo CI deadlock without compromising the immutability of merged satellite state.

**Divergent finding — Claude reconciliation call (Codex-only, narrow scope):**

**Codex C-1 (LOW): Poetry syntax variant.** Codex notes that legacy Poetry projects (`[tool.poetry.dependencies]` table style) would express the dep differently:

```toml
epicoracle-feedback = { git = "https://github.com/cdonovan-abtex/epicoracle-feedback-substrate.git", tag = "v0.2.0" }
```

- **Reconciliation**: not applicable to current EpicOracle Family satellites — all use PEP 621 (`[project].dependencies` array) + uv as the resolver, where the proposed string form (`epicoracle-feedback @ git+https://...@v0.2.0`) is canonical. Codex's concern is noted for future-proofing if any satellite ever adopts Poetry layout, but Wave B requires no action.

**Alternatives surfaced (out of scope for Wave B, recorded for future):**

- **Commit SHA pinning** (both reviewers): maximally reproducible, weaker version-readability. Use the tag-ref form for Wave B per existing convention; SHA pinning available as an opt-in for satellites that need strict reproducibility (e.g., a customer pilot deployment).
- **Private PyPI/package registry** (Gemini): cleaner long-term, but adds publishing infrastructure. Not in scope; revisit if substrate version cadence becomes high or if external operators need to consume the substrate.
- **Automated dep-update tooling (Dependabot/Renovate)** (Gemini): reduces operator toil on version bumps. Worth adopting once substrate version cadence stabilizes; not in scope for Wave B.

**Verdict on the amendment after reconciliation:** `accept` with the dev-time branch-ref workflow + tag-protection mandate + lockfile-refresh discipline folded in. Phase ordering remains correct.

#### v3 → v3.1 patch amendment (Docker-bridge admin origin, 2026-05-28)

This amendment closes a gap that surfaced at Phase 10 LLT deploy: **the v2 brief's "tailnet-only" admin origin check (100.64.0.0/10 source IP) fails for the hub satellite because the hub runs in Docker.**

Sequence of discovery:

1. v2 brief defined the admin auth gate as "request source IP must be in localhost (127.0.0.1, ::1) or tailnet (100.64.0.0/10)."
2. Marketplace + compliance satellites run as pm2-managed processes directly on the LLT host. Source IPs of inbound requests are preserved through to the satellite. Admin endpoint hits cleanly from external tailnet clients (verified Phase 10 — both returned HTTP 200 from MBP).
3. **Hub runs in a Docker container.** Docker's default bridge networking with userland-proxy rewrites the source IP of inbound requests to the bridge gateway (typically `172.17.0.1` or another address in `172.16.0.0/12`). So the in-container hub backend sees `172.17.x.x` as the source IP for ALL inbound requests, regardless of the original client.
4. Hub admin endpoint correctly fail-closed (403 "Admin route is tailnet-only") when hit from MBP via tailnet IP, because `172.17.0.1` is not in the tailnet range. Code did exactly what the brief specified; the brief just hadn't anticipated Docker's source-IP rewriting.

**Decision (Christian, 2026-05-28, Phase 10 incident):** patch substrate `_is_localhost_or_tailnet` to ALSO accept the Docker default bridge subnet (`172.16.0.0/12`). Tag substrate `v0.2.1`. Redeploy hub against the new ref. Marketplace + compliance also benefit from the additional CIDR but were already working pre-patch.

**Why this is safe:**

- `172.16.0.0/12` is **RFC 1918 private** — these addresses are not routable from the public internet. They can ONLY appear as source IPs when a request originates from a process on the same host (or a host in the same private network).
- For a Funnel-exposed satellite, traffic from the public internet enters via Tailscale Funnel ingress and gets routed to the local satellite. If the satellite runs in Docker, Docker's source-IP rewriting maps the public-internet source to the bridge gateway, NOT to a public IP. So accepting `172.16.0.0/12` does not open admin endpoints to the public internet — the public traffic always gets terminated by the frontend (which doesn't proxy admin paths) before reaching the backend.
- For a non-Funnel-exposed admin endpoint reached directly via the backend port (e.g., `100.92.108.122:3001/admin/...`), the source-IP rewriting still happens at the Docker layer, but only for requests that ACTUALLY originate from a Docker-private network. There is no path by which a public-internet client can produce a `172.16.0.0/12` source IP at the in-container code.

**Why this isn't trinity-vetted** (per `feedback_blast_radius_review_tier`): single-line extension to an existing CIDR check (narrow design space + existing pattern + no new architectural decision class). Test added; brief amendment documents the decision; substrate patch tagged as v0.2.1 (semver patch bump per the change being non-breaking).

**Affected files:**

- `src/epicoracle_feedback/admin_router.py` — added `DOCKER_PRIVATE = ipaddress.ip_network("172.16.0.0/12")` constant + `or ip in DOCKER_PRIVATE` to `_is_localhost_or_tailnet`
- `tests/test_admin_router.py` — added `test_admin_docker_bridge_origin_allowed`
- `pyproject.toml` — bumped to 0.2.1
- `CHANGELOG.md` — v0.2.1 entry
- Hub satellite — `epicoracle-feedback` ref bumped from `@v0.2.0` to `@v0.2.1`

Marketplace + compliance refs deliberately NOT bumped at this patch — they're not affected by the Docker constraint and a separate bump for them just to take the same dep version is operator overhead with no functional benefit. They pick up v0.2.1 on the next wave's dep bump per [[feedback_correct_beats_quick]] discipline.

#### v3.2 — Phase 10 finding: synthetic-admin auth gap on marketplace + compliance (deferred to production hardening, 2026-05-28)

While verifying Phase 10 deploys, surfaced that **marketplace + compliance admin endpoints accept any tailnet-source request as authorized admin**, without requiring credentials.

Root cause chain:

1. Both satellites' `_auth_enabled()` reads an env var (`EPICORACLE_MARKETPLACE_AUTH_ENABLED`, `EPICORACLE_COMPLIANCE_AUTH_ENABLED`). Both are `false` on LLT.
2. When auth is disabled, `get_principal(request)` returns `_synthetic_principal()` — a hardcoded dev-mode user with `SYNTHETIC_ROLES = (ROLE_OPERATOR, ROLE_ADMIN)`. Synthetic admin role is granted regardless of any credential.
3. The substrate's admin router checks `_has_admin_role(principal)`. Synthetic principal passes this check (`ROLE_ADMIN` is present). Router has no way to distinguish synthetic from real principals — it only sees the roles.
4. Net effect: admin endpoints on marketplace + compliance return 200 to any tailnet request, no credentials needed. The auth identity gate is effectively pass-through; only the network/tailnet gate is enforced.

Hub does NOT have this — its `_role_gate` (`resolve_admin_principal(Authorization, X-User-Role)`) returns None for unauthenticated requests, so the auth gate is real fail-closed.

**The v2 brief assumed** the satellite's `role_gate` would return None for unauthenticated requests. Two of three current satellites synthesize an admin instead.

**Decision (Christian, 2026-05-28, Phase 10):** accept the gap on marketplace + compliance for the current staging-tier posture. Defer hardening to when EpicOracle moves off Tailscale Funnel to its production-tier hosting (Beast Linux server, `epicoracle.abtex.com` or similar).

**Why this is acceptable for the staging tier:**

- The synthetic-admin behavior only fires for requests that reach the satellite's BACKEND port (3001 / 8001 / 8002 directly). External operators (John, Dan, anyone with the public Funnel URL) only have the public `https://` links — those route to FRONTENDS, which don't proxy admin paths. So admin endpoints are NOT reachable from public internet at all.
- Tailnet access is currently single-operator (Christian only — verified `tailscale status` 2026-05-28). Synthetic-admin-on-tailnet is functionally equivalent to "Christian only" since no other tailnet member exists.
- Even if a tailnet member were added (Vanessa, Josh) in the staging tier, the admin endpoint exposes read-only access-log data; no write surfaces, no destructive operations. Risk surface is limited to "another tailnet member could view who's hit which routes," not "another tailnet member could modify state."

**Production-hardening punch list (when Beast deploys + Tailscale Funnel retires):**

- [ ] Enable `EPICORACLE_MARKETPLACE_AUTH_ENABLED=true` + Entra app registration + bearer token validation
- [ ] Enable `EPICORACLE_COMPLIANCE_AUTH_ENABLED=true` + same
- [ ] Verify both satellites' `get_principal` paths require real auth headers and 401 (not 200 + synthetic) when unauthenticated
- [ ] Verify admin endpoints on both satellites return 403 (not 200) for unauthenticated requests after auth is enabled
- [ ] Optionally: substrate v0.x.y patch to refuse `principal.is_synthetic=True` in `_has_admin_role` (defense in depth — even if a satellite forgets to enable auth, admin endpoints still fail closed). Single-line patch, deferred to whenever this list activates.

**Why not patch substrate now**: per [[feedback_correct_beats_quick]] + [[feedback_blast_radius_review_tier]] — the staging tier is functionally safe right now, the operator deferred to a known future hardening point (Beast deploy), and patching now creates v0.2.2 + flip-all-satellites churn for zero current-state risk reduction. The fix belongs in the production-tier transition, not as a Wave B follow-on.

---

## Pre-flight notes

(Unchanged from v1 — Phase 0 discovery was complete before v1 drafted. Carried forward.)

Per [[feedback_pre_brief_discovery]]. Conducted 2026-05-27 12:30 EDT.

### Conventions checked
- [x] Satellite-template `AGENTS.md` — Architectural rules §1 (Schema-First), §2 (audit + sensitivity), §3 (LLM rules N/A), §4 (plugin routers), §5 (scale-fragility)
- [x] Satellite-template `WAVE_LIFECYCLE.md` — Trinity-vet activation criteria, bare-command git mechanics
- [x] Satellite-template `SATELLITE_CHECKLIST.md` — substrate-adoption checklist items
- [x] Substrate `README.md` + `CHANGELOG.md` (v0.1.0 Wave A — same architectural conventions apply)
- [x] Substrate `events.py` — existing observability primitive (preserved unchanged by v2)

### Precedent files cited
- **Observability hook pattern** — `epicoracle_feedback/events.py` (Wave A). Preserved; v2 adds a **parallel** `http_events.py` module rather than extending events.py.
- **Cross-boundary schema convention** — `core/schemas/` per template AGENTS.md §1.
- **Audit decorator pattern** — `@security_admin_audited` lineage; admin endpoints get `@security_admin_audited_read` (new sibling decorator) per Codex B-7.
- **Plugin router pattern** — `routers/` autoload per template AGENTS.md §4.
- **Sensitivity class enum** — `SensitivityClass` from satellite-template; INTERNAL default with per-route HIGH override.

### Data posture decisions
- **Real data committed**: Route templates + anonymized user identifier samples in tests. No real operator request logs committed.
- **Synthetic data**: Unit-test fixtures use synthetic users (`test-user-1@example.test`) and synthetic correlation IDs.
- **Excluded from commit**: Per-satellite SQLite access-log DBs (`data/access_log.sqlite`) gitignored.

### Operator question this wave answers
- **Real operator decision**: *"Is John (or any specific user) actually hitting the compliance satellite? When did they last visit? Are they hitting validation pages, or just the home dashboard?"*
- **Why current process can't answer it well**: No persistent HTTP access log on any satellite; visit-level engagement is invisible.
- **Why v2 answers it better**: SQLite-indexed access log with route-template paths, principal identity, timestamps, status codes — queryable in 5 seconds via `/admin/access-log/summary?since=24h`.

---

## Scope (v2)

### In:

1. **Substrate HTTP-events module** at `epicoracle_feedback/http_events.py`:
   - `HttpEvent` Pydantic model (frozen, extra="forbid") with name (`http.request.completed` | `http.request.errored` | `admin.access_log.read`), correlation_id (server-generated UUIDv4 by default; accept client `X-Request-ID` ONLY if matches `^[A-Za-z0-9-]{1,64}$`), and structured payload.
   - `register_http_event_sink(sink)` + `emit_http_event(event)` — parallel to Wave A's `events.py` but separate slot. Fail-soft per Wave A precedent.

2. **Substrate middleware module** at `epicoracle_feedback/http_middleware.py`:
   - **Pure ASGI middleware** (NOT `BaseHTTPMiddleware`) — per Codex N-5. Captures `(timestamp_utc, principal, method, route_template, status, duration_ms, response_size_bytes_or_None, correlation_id, tenant, client_ip)`.
   - **Async-safe by construction**: middleware schema-constructs and `await queue.put_nowait(event)` to a bounded `asyncio.Queue(maxsize=10000, configurable)`. **No sync I/O on hot path.**
   - Background drain task started at app startup via FastAPI `lifespan` hook; consumes queue, writes to SQLite store. On queue overflow: increment `dropped_events_counter` Prometheus-style metric and warn-log; never block the request.
   - Default exclude filter: **response Content-Type** based (`image/*`, `text/css`, `application/javascript`, `font/*`) — per Gemini OQ-2. Path patterns remain as configurable supplementary override.
   - **Mandatory path sanitization**: stores `request.scope["route"].path` (the FastAPI route template like `/api/satellites/{slug}`) NOT `request.url.path` (the raw matched URL). Query strings dropped entirely by default; allowlisted-key redaction available as configurable override.
   - Fail-soft: middleware errors NEVER block the response. Caught + logged + continue.

3. **Substrate access-log store module** at `epicoracle_feedback/access_log_store.py`:
   - `SqliteAccessLogStore(path)` — single persistence implementation, SQLite WAL mode.
   - Schema: indexed columns on `(timestamp_utc, principal, route_template, tenant, status)`. Pagination via cursor (`(timestamp_utc, correlation_id)` composite). Append-only on the write path (no UPDATE/DELETE except retention).
   - **Hard retention default**: 100k entries OR 100MB per satellite (whichever first); enforced by background task that runs hourly. Configurable via env vars `EPICORACLE_HTTP_LOG_MAX_ENTRIES` / `EPICORACLE_HTTP_LOG_MAX_BYTES`. **Surface to Christian at Phase 4 for ratification.**
   - Read API: `query(filters, cursor, page_size)`, `summary(window)`, `count(filters)`.

4. **Substrate admin router** at `epicoracle_feedback/admin_router.py`:
   - `build_access_log_router(store, *, role_gate, rate_limiter, audit_emitter)` factory — returns FastAPI `APIRouter`. Satellites mount at `/admin/access-log`.
   - Endpoints:
     - `GET /admin/access-log` — paginated, filterable by `principal`, `route_template`, `since`, `until`, `status_min`, `status_max`. Default lookback 24h, max page size 50 (configurable up to 200), required tenant scope (auto-derived from auth principal's tenant).
     - `GET /admin/access-log/summary` — aggregations: unique principals, last-visit-per-principal, visits-per-route-template, p50/p95/p99 latency per route, dropped_events_counter (for visibility into overflow).
   - **Fail-closed authentication**: no default permissive role gate. Dev-mode `X-Entra-Stub-User` accepted ONLY when `EPICORACLE_DEV_MODE=true` env var explicitly set AND request origin is localhost or tailnet (100.64.0.0/10).
   - **Per-principal rate limit**: 60 req/min (Codex B-4 requirement).
   - **Audited reads**: every admin endpoint hit emits `admin.access_log.read` on the **feedback-events sink** (Wave A path, NOT the HTTP-events sink). No recursion possible (Codex B-7 fix).

5. **Substrate schemas** at `epicoracle_feedback/schemas/observability.py`:
   - `AccessLogEntry` (frozen, extra="forbid", all timestamps UTC tzinfo, Field constraints on method/status/duration_ms/response_size_bytes).
   - `AccessLogPage` (entries + next_cursor + total_count).
   - `AccessLogSummary` (the aggregation response).

6. **Satellite adoption — hub, marketplace, compliance**:
   - Each satellite's `backend/app/main.py` adds the ASGI middleware via `app.add_middleware(...)` (single line, env-gated) and registers a `SqliteAccessLogStore` sink at startup via lifespan hook.
   - Each satellite's `backend/app/routers/admin.py` mounts the substrate's `build_access_log_router` with the satellite's existing role-gate function.
   - **Per Christian's Phase 4 decision on admin-on-Funnel**: admin router is either (a) hard-disabled, (b) tailnet-IP-gated, or (c) auth-shimmed. Default in v2 is (b).

7. **Template inheritance**:
   - `epicoracle-satellite-template/backend/app/main.py` adds middleware registration with `EPICORACLE_HTTP_LOG_ENABLED=false` default.
   - `epicoracle-satellite-template/backend/app/routers/admin.py` — new scaffold file with substrate-mount call commented + clear instruction to wire when adopting.
   - `epicoracle-satellite-template/SATELLITE_CHECKLIST.md` — new checklist items: "Wire substrate access-log middleware. Flip `EPICORACLE_HTTP_LOG_ENABLED` to true. Verify `/admin/access-log/summary` returns 200 with at least 1 entry after first request. Confirm admin endpoint network gating per project's Funnel/tailnet decision."

### Out (deferred to later waves):

- **Validation-progress server-side persistence** — moved out per D-5 (Gemini's separation-of-concerns critique). Becomes a separate compliance-internal wave (compliance-W3 candidate) if Christian ratifies the scope cut at Phase 4.
- **Real Entra bearer-token auth on admin endpoints** — W2-scope existing TODO; v2's fail-closed dev-mode + tailnet-gated default is the bridge until then.
- **Tailscale Funnel-level access logs** — Tailscale's own surface; outside substrate scope.
- **Log retention/rotation policy beyond hard cap** — Wave B provides the hard cap; per-environment fine-tuning via env vars; longer-term retention/archive is operator-policy.
- **Cross-satellite admin views** — single-pane-of-glass dashboard aggregating logs across satellites. Deferred; would belong in the hub as a separate feature.
- **Scoped `audit_viewer` role** — deferred per D-4 (YAGNI).
- **Path/query parameter redaction allowlist UI** — substrate ships the redaction mechanism; per-satellite configuration is operator/dev task, not substrate-shipped UI.

---

## Architectural rules to honor

1. **Schema-First (template AGENTS.md §1)** — `epicoracle_feedback/schemas/observability.py` is the single source. Satellites import; do NOT redefine.
2. **Sensitivity classification (template AGENTS.md §2)** — `AccessLogEntry.sensitivity = SensitivityClass.INTERNAL` default; per-route HIGH override configurable.
3. **LLM rules (template AGENTS.md §3)** — N/A; no LLM components.
4. **Plugin architecture (template AGENTS.md §4)** — admin router via `routers/`; middleware registered in main.py via documented single-line exception.
5. **Scale-fragility (template AGENTS.md §5)** — SQLite WAL handles concurrent writes; bounded `asyncio.Queue` prevents memory bloat under burst; hard retention cap prevents disk exhaustion; indexed columns prevent query degradation.
6. **Observability-never-breaks-flow (Wave A precedent)** — middleware errors caught + logged + continue. Queue overflow drops events + increments counter; never blocks.
7. **Tenant-aware** — `AccessLogEntry.tenant` populated from satellite config; admin endpoints filter by tenant.
8. **Admin endpoints are fail-closed-by-default audit surfaces, not convenience views** (Codex B-4 absorbed) — no permissive defaults, rate-limited, default lookback windowed, page-size capped, every read audited.

---

## Operational contract (v2 — tightened)

- **Bounded concurrency**: Middleware enqueues to `asyncio.Queue(maxsize=10000)` — bounded. Background drain task is single-consumer (no race). Admin endpoints are read-only.
- **Rate-limit policy**:
  - Middleware: fire-and-forget via `queue.put_nowait`. On `QueueFull`: drop event, increment counter, log at warning. NEVER block.
  - Admin endpoints: per-principal 60 req/min via in-process rate limiter (configurable).
- **Partial-success semantics**: SQLite WAL provides ACID at the row level. Sink failures (rare) are logged + counter-incremented. Reader queries skip nothing (no malformed rows possible with SQLite).
- **Idempotency**: Append-only on writes; `correlation_id` is functionally unique (server-generated UUIDv4 default; validated if client-provided). Reads are idempotent by query construction.
- **Observability events emitted**:
  - `http.request.completed` (every non-excluded request, on HTTP-events sink)
  - `http.request.errored` (middleware itself errored — diagnostic for the substrate)
  - `admin.access_log.read` (admin endpoint hit, on **feedback-events sink** — non-recursive by design)
- **Tenant guard**: `AccessLogEntry.tenant` auto-populated from auth principal's tenant. Admin endpoints filter by tenant before pagination. Cross-tenant queries return 403.
- **Accessibility**: Admin UI is small surface (table + filters). WCAG AA — keyboard navigation, focus management, screen-reader labels.
- **Error budget**: Middleware MUST NOT increase request error rate. Acceptable additional latency: <2ms p50, <5ms p99 (tightened from v1's <10ms). Measured via post-deploy probe before LLT validation passes.
- **PII contract**:
  - `path` field = route template, NOT raw URL.
  - Query strings dropped by default.
  - `principal` field MAY contain operator email (PII). Sensitivity routing handles this.
  - `client_ip` field MAY be redacted to /24 in INTERNAL sensitivity per IT policy (configurable).
  - NO request/response body capture, ever.

---

## Pydantic schemas (v2)

`epicoracle_feedback/schemas/observability.py`:

```python
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

class HttpEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    name: Literal["http.request.completed", "http.request.errored", "admin.access_log.read"]
    correlation_id: str = Field(..., min_length=1, max_length=64, pattern=r"^[A-Za-z0-9-]{1,64}$")
    timestamp_utc: datetime
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("timestamp_utc")
    @classmethod
    def must_be_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.utcoffset().total_seconds() != 0:
            raise ValueError("timestamp_utc must be timezone-aware UTC")
        return v

class AccessLogEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    correlation_id: str = Field(..., min_length=1, max_length=64)
    timestamp_utc: datetime
    principal: str | None = Field(None, max_length=320)  # email or auth-id; None for unauthenticated
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]
    route_template: str = Field(..., min_length=1, max_length=512)  # NOT raw URL; route template
    status: int = Field(..., ge=100, le=599)
    duration_ms: int = Field(..., ge=0)
    response_size_bytes: int | None = Field(None, ge=0)
    tenant: str = Field(..., min_length=1, max_length=64)
    client_ip: str | None = Field(None, max_length=64)  # may be /24-redacted per IT policy
    sensitivity: SensitivityClass = SensitivityClass.INTERNAL

class AccessLogPage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entries: list[AccessLogEntry]
    next_cursor: str | None
    total_count: int = Field(..., ge=0)

class AccessLogSummary(BaseModel):
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
```

`ValidationProgressEntry` is **removed from substrate schemas** per D-5. If compliance-W3 ships validation-progress, it owns its own schema in `epicoracle-compliance/backend/app/schemas/`.

---

## Acceptance criteria (Phase 11 — operator validation on live URL)

1. **Hit any satellite's API and verify the request appears in `/admin/access-log` within 2 seconds.** Verify `route_template` is the route pattern, not raw URL with query params.
2. **Hit the same satellite with a different user identity and verify both principals surface in `/admin/access-log/summary`** with correct last-visit timestamps + latency aggregations.
3. **Hit a static asset (e.g., `/_next/static/...`) and verify it does NOT appear in the log** (Content-Type exclusion working).
4. **Hit the admin endpoint from a non-tailnet origin** and verify 403 (admin-on-Funnel security gating works — per Christian's Phase 4 decision).
5. **Inspect the SQLite access-log on LLT compliance** — verify schema matches `AccessLogEntry`, timestamps are UTC, no query strings in path field, no raw request bodies captured.
6. **Burst-test**: Hit a satellite with 1000 requests/second briefly. Verify request error rate is unchanged and `dropped_events_counter` increments cleanly without blocking responses.
7. **Hit admin endpoint 61 times in one minute as the same principal** — verify 429 on the 61st (rate limiter works).
8. **Inspect retention behavior**: With `EPICORACLE_HTTP_LOG_MAX_ENTRIES=100` set, verify oldest entries are pruned when 101st arrives (retention enforcement works).

### Test acceptance for Codex B-8 (explicit fail-soft branch coverage)

Required unit + integration tests:
- Middleware sink-failure path (sink raises → request still succeeds, error logged)
- Queue overflow (full queue → put_nowait raises QueueFull → counter increments + warning logged → request unblocked)
- Malformed correlation_id from client (non-matching regex → server-generated UUID used)
- Admin auth denied (invalid stub-user, non-dev-mode, non-tailnet origin → 403)
- Tenant leakage (cross-tenant query → 403)
- Oversized request handling (large query string → still stored as path-only template, no PII leak)
- SQLite WAL concurrent writers (2 workers × 1000 requests each → all rows present, no corruption)
- Retention enforcement (max_entries exceeded → oldest pruned, counter accurate)

---

## Cleanup criteria (Phase 12-13)

- Worktree removed from `~/Developer/epicoracle-feedback-substrate-worktrees/wB/`
- Branch `feat/wB-observability-substrate` deleted local + origin after merge
- Satellite branches (`feat/wB-adopt-observability` on each of hub/marketplace/compliance) deleted same
- Template branch (`feat/wB-template-inherit`) deleted same
- v2 brief committed at Phase 3 (this commit); future revision commits if scope mutates
- Activity-log Active-threads digest refreshed: Wave B done, Wave C placeholder (TBD)
- New memory file `feedback_observability_substrate_pattern` capturing the design (for future satellites' AGENTS.md cross-references) — includes the validation-progress-is-domain-state lesson
