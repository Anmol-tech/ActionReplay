# Implementation and verification map

This preserves the agreed scope and distinguishes implementation from live verification. README contains the commands; REPORT contains the seven required design sections.

| Agreed subsystem | Implementation and verification |
|---|---|
| Python stack and reproducible setup | pyproject.toml, uv.lock, package CLI; installation and process-level smoke test pass. |
| Local legacy app | Nested frames, tables, unlabeled select, synthetic member/account/form screens; transfer/create/delete with irreversible confirms blocked; both easy and hard workflows traversed in Chromium. |
| No business API discovery | Screenshots/rendered controls and fixed browser tools only; hidden-content exclusion test. No production task scripts. |
| Real model discovery | OpenRouter image/tool preflight and validated tool-call adapter; protocol tested with mocked HTTP. **Genuine provider discovery exported under `/evidence/` (live provenance).** |
| Generic discovery loop | Fresh observations, action validation, runtime outcomes, no-progress detection; offline model doubles exercise two live UI workflows. |
| Configurable 30-step default | Config and CLI step/time overrides; precedence, invalid values, rejected-decision accounting, and explicit extensions tested. |
| Typed replay schema | Pydantic discriminated union and exported JSON Schema; round-trip, version/action/field, reference, ordering, and contract validation. |
| Parameterized recording | Input/literal/variable bindings and stable frame-scoped targets; recorded artifacts replay with different member and form inputs. |
| Immutable artifact storage | Exclusive revisions, exact run copies, canonical SHA-256; overwrite and hash verification tests. |
| Deterministic interpreter | No discovery/model imports in replay.py; optional AssistedFallback injected by the server; actions, conversions, checkpoints; model access disabled during default replay tests. |
| Business outcomes | Explicit not-found, invalid member/nickname, and missing-account detectors; not-found and invalid-member paths tested. |
| Recoverable conditions | Bounded safe waits/retries and known handlers; slow, transient, interstitial, and zero-recovery tests. |
| Hard failures and targeting | Permission failure, incompatible app/version, unique targeting; denied access, startup mismatch, and duplicate-control tests. |
| Safety | Route/origin/action/control allowlists and approved artifact literals/attributes; real side-effect and network-block tests. |
| Same-session takeover | Single-owner PAUSED/HUMAN state machine; context/tab/cookie continuity and automation exclusion verified. |
| Resume validation | Pre/postconditions, live browser, valid routes, no unresolved dialogs/popups; invalid resume stays paused, stale requests rejected. |
| Human action evidence | Redacted UI events/navigation/ownership; simulated operator events captured on the same session. |
| Operator and discovery interface | Loopback-origin-protected discovery form and handoff controls; origin tests, exact discovery payload test, CLI/server/browser smoke test, visual QA. |
| Observability | Validated JSONL, manifests, results, sanitized snapshots; sequences and hashes verified. |
| Sensitive data | Known-value/secret redaction, approved snapshot vocabulary, transient screenshots, redacted persisted outputs; canary tests. |
| Persistence failures | Evidence-write failure stops actions; incomplete manifests remain incomplete; fault-injection test. |
| Export and retention | Completed-run export/scanning and explicit retention cleanup; active runs/capabilities/exports preserved. |
| CLI | serve/discover/replay/export-evidence/cleanup/schema; actual CLI receives expected JSON from coordinator. |
| Required deliverables | README.md, REPORT.md, schemas, examples, /evidence included. |
| Heterogeneity and tenants | Surface seam, compatibility declarations, documented reviewed overrides; design only beyond the browser profile. |

## Evidence provenance

Live OpenRouter discovery, alternate-input replay, and a not-found business outcome are exported under `/evidence/` with `provenance: live`. Additional offline examples demonstrate recording, same-session handoff, and transient recovery; every offline manifest and the index identify offline model/fixture provenance. Human takeover in offline examples is simulated by the test harness and logged as such.

## Deliberate limits retained from the plan

One local run/operator, synthetic data, file storage; no remote streaming, desktop implementation, distributed workers, tenant plumbing, polished dashboard, universal PII classifier, or automatic artifact repair. Bounded LLM-assisted replay (`assisted_fallback`, max one policy-checked step) is optional stretch recovery for UI drift — not open-ended re-discovery. Completing goals auto-pause at irreversible Confirm*; review/confirmation-screen goals may finish without Confirm. A new target requires an explicitly adapted trusted UI profile. A bank deployment additionally requires review of model-visible data, control semantics, authentication, and operator identity.

## Verified commands

```bash
uv run pytest -q
uv run ruff check actionreplay tests scripts
uv run python scripts/build_demo_evidence.py
```

At implementation handoff: 36 tests passed, including Chromium and CLI integration; lint clean. The evidence builder requires local browser/server permissions and labels generated examples offline.
