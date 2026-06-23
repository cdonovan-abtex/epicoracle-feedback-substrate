> **CAPTAINS-INTENT.md** — the durable WHY for `epicoracle-feedback-substrate`. This file explains the intent a change must serve; it does not explain how the code works. The HOW — build commands, module layout, contracts, security mechanics, runbooks — lives in `AGENTS.md`. As an EpicOracle Family satellite, this repo inherits the family's WHY (a satellite is valuable alone and 10x more valuable connected; the org learns from every action) and adds its own job: turn raw operator feedback into a governed GitHub flow that the agent fleet can act on under a human gate. When intent and mechanics disagree, intent wins and `AGENTS.md` gets corrected.

## ★ North Star

A non-technical operator, anywhere, can press one button to report a bug, suggest an improvement, or ask a question — and that single act becomes a structured, idempotent, security-bounded GitHub Issue that the agent fleet can research and fix autonomously, while a human stays the only gate to merge, and the operator watches it move from *submitted → processing → fix-ready → deployed* without ever picking up a phone. The substrate collapses the operator-to-fix loop from an interruption-driven phone call into a calm asynchronous queue. It is shared infrastructure, not a one-off: it is factored once, hardened once, and inherited by every family satellite and every future fork, so the whole family improves the same way and the captain reviews instead of re-builds.

## The 5 Whys

1. **Why does this repo exist?** Because operator feedback today arrives as an interruption — a phone call, a tap on the shoulder, an email — and dies in someone's memory. We need it captured as structured, trackable work the moment it happens.
2. **Why must capture be structured and trackable?** Because untracked feedback can't be queued, can't be routed to an agent, can't show the operator that anything happened, and can't be audited later. A GitHub Issue is the throughput unit — it makes the work visible, dispatchable, and permanently logged.
3. **Why route it to agents at all instead of just logging it?** Because agent throughput vastly exceeds the captain's dispatch rate when work is tightly scoped. The bottleneck is queue depth, not compute. Turning feedback into well-formed issues feeds a queue that agents drain in parallel — so fixes ship without the captain hand-carrying each one.
4. **Why keep a human as the merge gate if agents do the work?** Because agents do the labor; humans hold the judgment. Investigate-then-fix with a mandatory human approval between them is the entire safety model. The operator's text is untrusted data, the agent's output is a proposal, and nothing reaches `main` or production without the captain's review. Autonomy without that gate is how trust dies.
5. **Why build it as a shared, inheritable substrate rather than inline in each app?** (root) Because the family's whole premise is that you build the capability once, correctly, and every member inherits it — so the org learns the same way everywhere, corporate migration is a config swap not a rewrite, and a fix to the substrate is a fix for the entire family at once. The root is: **leverage through shared, sovereign, governed infrastructure — the captain reviews and the fleet executes, forever.**

## The Heart

The irreducible core — what must always stay true no matter how the implementation evolves:

- **One button, any operator, any surface.** If a non-technical person can't report a problem in one tap and trust it was heard, the substrate has failed its reason for being.
- **Capture never blocks.** Feedback is fail-soft. If GitHub is unreachable, the submission is queued locally and replayed later — the operator is never told "try again." Losing a piece of feedback is the cardinal sin.
- **The human is always the gate.** Agents investigate and propose; a human approves before anything merges or deploys. This gate is not a feature to optimize away — it is the load-bearing wall.
- **Operator text is data, never instruction.** Untrusted input is fenced and treated as content for the entire pipeline. The moment operator text can steer an agent or a workflow, the substrate is compromised.
- **The operator sees state.** Submitted work shows its status back in-app. Without a visible loop, operators stop trusting the button and revert to the phone — which defeats the whole point.
- **Build once, inherit everywhere.** This is shared infrastructure. Logic lives in the substrate; satellites carry thin wiring. Per-tenant differences are config, never forked code.

## Lessons

- **Queue depth is the bottleneck, not agent capacity.** The captain's role is queue-feeder and reviewer; the substrate exists to keep the queue well-formed and flowing.
- **Investigate-then-fix beats fix-on-sight.** A human reading the proposed approach *before* the fix runs is the gate operationalized — collaboration, not automation replacing decisions.
- **A private repo is storage, not privacy.** Real protection is classification, scrubbing of obvious secrets at intake, and access control — never "it's a private repo."
- **Untrusted content through `env:`, never inline interpolation.** Operator and issue text reaches scripts as environment values, not spliced into command lines. This is non-negotiable, structural injection prevention.
- **Agents get a termination ceiling.** Bounded attempts, then hand to a human. Unbounded retry is a failure mode, not persistence.
- **Idempotency is designed in, not bolted on.** A client-generated submission identity makes replay and dedup safe by construction; retry must never create duplicate work.
- **Defer operator visibility at your peril.** The status loop is part of the minimum viable product, not a later nicety — without it the button loses trust.
- **The audit trail is free if you let the issue thread be it.** Investigation, refinement, fix, verification all live in one place — kintsugi capture with no extra ceremony.
- **Reproduction is evidence, not proof of correctness.** A repro shows the bug exists; the fix still has to carry tests for the layer it touches.

## Boundaries

**Governance Tier: 2.** This is an Abtex Intelligence satellite that touches operator-submitted content, drives writes to family repos (some of which carry ERP/customer/financial-adjacent surfaces), and runs autonomous agents. It sits at the Tier-2 floor: role/credential scoping, audit on writes, pull-and-propose-only-by-default with an explicit human gate before any merge or deploy, tested rollback, and a documented incident/runbook posture.

**In scope:**
- Capturing operator bug/suggestion/question feedback from any family surface into governed GitHub Issues.
- Idempotent, fail-soft dispatch with local queue + replay when GitHub is unreachable.
- Classifying feedback and routing it to the appropriate autonomous agent path.
- Bounded, sandboxed agent investigation/repro and human-gated fix proposals (PRs).
- Surfacing processing status back to the operator in-app.
- Providing the shared package, workflow templates, and wiring that satellites and forks inherit.

**Out of scope — deliberately NOT this repo's job:**
- Merging or deploying without a human gate. Never.
- Being a drill-down or analytics layer — this is a feedback flow, not a dashboard.
- Treating operator text as anything other than untrusted data.
- Hard-coding repo names, tenant identity, or credentials — all of that is config.
- Owning the satellites' domain logic; it provides the feedback rail, not the destination apps.
- Privacy-by-storage. Classification and scrubbing belong here; "it's private" is not a control.

**Always escalate (stop and surface, don't decide):**
- Any change that weakens or bypasses the human merge gate.
- Any change to security-critical surfaces (workflow files, the untrusted-input handling boundary, the path-allowlist guard, credential scoping, branch protection).
- Any feedback or fix that touches authentication, tenancy, deployment, or customer/financial-adjacent surfaces — these route to multi-reviewer judgment, not single-agent autonomy.
- Architectural decisions surfaced during investigation — agents flag and escalate; they do not redesign.

## Definition of Success

- An operator reports a problem in one tap and sees it acknowledged and tracked — no phone call, no lost feedback.
- Feedback survives a GitHub outage: it queues locally and replays without the operator noticing.
- Well-formed issues flow into a queue that agents drain in parallel, faster than the captain could hand-dispatch.
- Every fix that reaches `main` passed a human review; nothing self-merges.
- The operator can watch their item move through states to "deployed" in-app.
- Operator text never acts as instruction; obvious secrets are rejected at intake.
- The substrate is factored once and inherited by satellites and forks via thin wiring — a fix to the substrate fixes the family.
- Corporate/tenant migration is a config and auth swap, not a code change.

## Tie-Back Test

For any change, ask: **Does this make operator feedback flow into governed, human-gated, fleet-actionable work more reliably — while keeping the human as the only merge gate, treating operator input as untrusted data, never losing a submission, and keeping the leverage shared across the family?** If a change weakens the human gate, lets operator text steer the system, risks dropping feedback, or forks logic that belongs in the substrate, it fails — regardless of how clever it is.

## Mechanics

The HOW lives in `AGENTS.md` (and the repo README/runbooks) — build/test commands, the package interface, the issue/label schema, the agent-dispatch workflow, sandbox repro, branch protection, secret scoping, rollback, and network-egress policy. This file does not duplicate them; if they drift, correct `AGENTS.md`, not the intent.

As an EpicOracle Family satellite, this repo **inherits the four-part contract** — *standalone-usable · event-publishing · MCP-exposing · tier-compliant* — and the **five first principles**: *Apple aesthetic · grandmother test · clean code · proven-tools foundation · experimentation reserved for the algorithms*. The feedback button and status loop are held to the grandmother test; the foundation uses boring proven tools; the experimentation budget is spent on classification and agent routing, never on the auth flow or the framework. Per-tenant identity, repo routing, and credentials are `target_cfg`/config, never code.
