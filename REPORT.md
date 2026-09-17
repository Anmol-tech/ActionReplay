# Architecture

ActionReplay separates probabilistic discovery from deterministic execution. A Python coordinator owns one Chromium context and a loopback-only local operator service; the CLI submits work and polls results. A separate FastAPI application supplies a synthetic legacy banking surface with nested frames and tables. A single-process coordinator avoids distributed locks and queues while making browser ownership explicit. The operator API accepts requests only from loopback hosts and the operator page origin; it does not use a shared URL token.

Discovery sends screenshots and rendered control descriptions to OpenRouter. It exposes a finite set of UI actions, not application business APIs, source code, network response bodies, hidden inputs, or arbitrary code execution. Observation references are temporary. The recorder resolves them into durable targeting descriptions and records successfully executed actions, parameter bindings, and verified checkpoints. Page text is untrusted data. A separate replay module imports no model client.

A genuine OpenRouter discovery run against the live mock UI is checked in under `/evidence/` (provenance `live`), along with alternate-input replay and a `MEMBER_NOT_FOUND` business-outcome replay. Offline scripted-model evidence remains for handoff/transient demos that do not require a provider call.

# Artifact schema

Pydantic defines and exports the executable JSON schema. A capability has schema version, immutable identity/revision, application compatibility requirements, typed inputs and outputs, reusable targets, ordered typed actions, known outcome rules, and final success conditions. Bindings distinguish invocation inputs, approved literals, and extracted variables. Member IDs are strings; decimal outputs are canonical strings rather than binary floats.

Targets preserve frame context and role/label/text or anchored table relationships. The schema contains no executable Python, JavaScript, selector-expression language, or model transcript. Extraction uses fixed text/integer/decimal/USD conversion functions. Validation rejects unknown actions, fields and schema versions, dangling references, duplicate steps, and variables used before extraction. A target must resolve uniquely. Artifacts cannot override runtime permissions.

Capability revisions are published without overwriting existing revisions. Each run stores the exact artifact and its canonical SHA-256 hash. Input values and extracted balances are not saved. A calling agent can invoke replay with typed arguments and receive success outputs, a business outcome, or a structured failure; a network capability catalog is deliberately deferred.

# Determinism & error handling

Replay interprets a bounded action vocabulary with no model fallback. Playwright supplies control actionability checks; the engine adds unique targeting, preconditions, postconditions, final checks, and bounded outcome polling during transitions. This matters because a navigation can produce an error screen just after an initial outcome check. Successful clicks alone never establish successful completion.

Rules distinguish business results such as member-not-found and invalid input from recoverable interstitials/transient errors and hard failures such as permission denial. Recovery counters are bounded; recovery actions cannot recursively invoke handlers. Only safe reads, waits, and reversible field-setting operations receive automatic retries. Potentially committed actions are not blindly repeated. Unknown dialogs, session expiry, and ambiguous targeting pause for intervention. Optional assisted fallback (off by default) may attempt one policy-checked LLM action on replay target drift, then returns to deterministic execution.

Discovery steps/time/no-progress limits and replay action/recovery limits are configurable. Rejected model decisions consume the step budget. Human pauses have a separate timeout and are excluded from discovery time. An exhausted budget needs a new explicit operator extension. Evidence records the effective limits.

# Heterogeneity & multi-tenant

The `SurfaceAdapter` seam separates observation, target resolution, actions, conditions, and extraction from flow interpretation. Browser support is implemented. A desktop accessibility or deterministic visual adapter would add target variants without introducing model decisions into replay. Raw coordinates are intentionally not a default replay target; supporting opaque pixels requires a separately engineered deterministic visual matcher.

A production deployment would keep a vendor/application-family capability separate from tenant base URLs, secrets, policy, and reviewed overrides for labels, frames, and routes. The current implementation includes application family/version declarations and a visible startup marker; incompatible configurations fail. It does not claim automatic cross-tenant compatibility. Reviewed overrides should produce a new effective revision/hash, with compatibility probes and replay evidence before promotion. Thousands of tenants need worker isolation and scheduling later, not in this vertical slice.

# Escalation & handoff

The coordinator maintains `AUTOMATION`, `PAUSED`, `HUMAN`, and `FINISHED` ownership. There is one action worker; escalation occurs after in-flight work settles. An intervention includes identity, current step, reason, goal/capability context, and sanitized structural evidence. Take Control releases the existing browser to the local operator. No fresh tab/context or authentication reset is involved.

Stuck/blocked detection covers budget exhaustion, no-progress, policy/target failures, unexpected dialogs, and irreversible Confirm* steps. Completing goals (create/transfer/delete/open after confirmation) auto-pause when a Confirm* control appears so a human commits the change on the same session; assignment-style “reach the confirmation screen” / review-only goals may finish on the review screen without confirming. Automated clicks of Confirm* always raise `HUMAN_CONFIRMATION_REQUIRED`.

The operator resolves the issue in that browser and selects Resume (or **I've confirmed — Resume** after a Confirm handoff). Automation cannot act during human ownership. Resume verifies a postcondition, a safe precondition, or — for Confirm handoffs — that the review screen was left; an incompatible state remains paused. Human click, field-change, and navigation events are recorded with values redacted. Native dialogs can be explicitly dismissed by the operator. Manual activity does not silently rewrite a capability. Abort and intervention timeout terminate clearly. Tests and checked-in evidence simulate an operator and label that fact; the operator page itself supports real local takeover.

# Safety

Trusted runtime policy checks origins/routes, action types, control identities, and approved artifact constants. Network routing also blocks off-policy browser requests, including frames/popups. Reads and reversible preparation are permitted; irreversible Confirm* commits are reserved for the human operator (block + same-session confirmation). Model-supplied intent or artifact claims cannot grant permission. The mock contains synthetic data only.

One evidence writer validates/sanitizes durable events, flushes them, and atomically writes complete JSON documents. Failure snapshots contain structural controls and approved status text, not arbitrary page content. Raw screenshots remain transient; transcripts, traces, HTML dumps, browser storage, secrets, and financial outputs are not persisted. Actual outputs return only through the local caller path. Evidence failure stops automation; a crash remains visibly incomplete. Export scanning and explicit retention cleanup provide additional safeguards.

Limits: screenshots sent to the model can contain visible data, so the current workflow must stay synthetic. Allowlisted control names require trusted application configuration; labels alone cannot prove semantic safety on an adversarial application. The instrumentation records browser UI events, not every OS-level action. Redaction combines known sensitive values and approved structural vocabulary; it is not a production universal PII detector. The loopback console is not a remote multi-user security product.

# Cuts

Deferred: remote streaming, desktop/visual implementations, distributed workers, tenant plumbing, polished multi-user UI, automatic artifact repair, confidence/approval promotion, a network capability catalog, and production identity/PII systems. Optional stretch **assisted fallback** is implemented but off by default (`execution.assisted_fallback`): at most one policy-checked OpenRouter recovery step on replay UI drift, never open-ended rediscovery. No submission email has been performed from this workspace.

Next steps are repeated multi-run stability evaluation and one reviewed application variant for cross-tenant overrides. Only after those pass would approval gating and a callable capability catalog be worth adding.
