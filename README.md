# ActionReplay

Discover a UI workflow with an LLM, save a typed capability, and replay it without a model. When automation cannot safely continue, a local operator takes control of the **same live Chromium session**.

Python 3.11+, Playwright, Pydantic, FastAPI, OpenRouter. No target business APIs, hidden application state, task-specific discovery scripts, or generated executable code.

**Evidence status:** the checked-in demonstrations use a clearly labeled offline model double with a real browser. Genuine OpenRouter discovery has not been run because this workspace has no configured API key/model. Completing that run is required before submitting this assignment. The offline double is only in tests and the evidence-building script; production discovery always calls OpenRouter.

## Setup

```bash
uv sync --extra dev
uv run playwright install chromium
cp config.example.yaml config.yaml
```

`uv.lock` pins the resolved dependencies. Python 3.11 is the minimum; `uv` creates the virtual environment. Install `uv` first if it is unavailable.

Supply credentials to the **server process**, not only the CLI client:

```bash
export OPENROUTER_API_KEY='your-key'
export OPENROUTER_MODEL='your-image-and-tool-capable-model-id'
uv run actionreplay --config config.yaml serve
```

Alternatively, populate a local ignored `.env` from `.env.example`, then load it into the shell before starting the server. The application deliberately does not load arbitrary environment files automatically. Never commit a key or paste it into a goal.

OpenRouter discovery preflights `/models` for image input and tool-calling support. It validates every returned action with Pydantic, requires provider parameter support, and requests providers that disallow data collection. An unavailable compatible provider produces a bounded failure/intervention. There is no silent substitute model.

The mock listens on `127.0.0.1:8000`; the coordinator/operator page uses `127.0.0.1:8001`. `serve` prints the operator URL with a local token in the URL fragment. Open that complete URL. The token is also stored with mode 0600 in ignored `.actionreplay/token`; the CLI reads it automatically. Browser outputs remain in process memory and token-authenticated responses only.

### Start discovery from the UI

The operator page also contains a **New discovery** form, so a second terminal is optional. Open the complete Operator URL printed by `serve`, then provide:

- the natural-language goal,
- the allowed target URL,
- a lowercase capability name,
- named inputs as a JSON object,
- the step and time limits.

Select **Start discovery** and watch the live status on the same page. If intervention is required, its Take Control and Resume controls appear alongside the run. After success, the page shows the returned outputs and the capability/run artifact locations. The API key stays in the server process and is never sent to or displayed by the page.

The server terminal streams sanitized lifecycle events as JSON, including browser startup, model preflight, observations, model requests, requested actions, rejected decisions, interventions, and the final result. Input values and the OpenRouter key are redacted. For stack traces during local debugging, put the global logging option before the command:

```bash
uv run actionreplay --log-level DEBUG --config config.yaml serve
```

Every streamed run event is also flushed to `runs/<run-id>/events.jsonl`. The terminal log is diagnostic output on stderr; command results remain structured JSON on stdout.

OpenRouter authentication, credit, provider-routing, rate-limit, and upstream errors receive distinct stable codes. A provider-routing 404 ends as `OPENROUTER_NO_PROVIDER`; it does not consume the discovery no-progress budget. Requests require image input, `tools`, and `tool_choice`. The client omits optional provider-specific parameters that the selected model does not advertise.

The existing CLI commands remain useful for repeatable demos and scripting.

## Genuine discovery, then replay

In another terminal, from this repository:

```bash
uv run actionreplay discover \
  --goal 'Find the savings balance for the supplied member' \
  --target http://127.0.0.1:8000 \
  --inputs-file examples/member-a.json \
  --capability savings-balance \
  --max-steps 40
```

Successful discovery writes `capabilities/savings-balance/1.json` (or the next immutable revision). It prints a run ID to stderr and a structured result to stdout.

```bash
uv run actionreplay replay \
  --artifact capabilities/savings-balance/1.json \
  --inputs-file examples/member-b.json
```

Expected output for member B is `9876.54`, represented as a decimal string. Replay imports no model client and requires no model key. The artifact uses a `member_id` input reference rather than storing member A's ID.

A different goal exercises form preparation:

```bash
uv run actionreplay discover \
  --goal 'Prepare a sub-account for the supplied member using account_type and nickname. Stop at review and return the displayed nickname.' \
  --target http://127.0.0.1:8000 \
  --inputs-file examples/subaccount.json \
  --capability subaccount-review
```

The agent chooses the sequence from screenshots and rendered controls. The banking mock provides screens/buttons; it does not provide a discovery recipe. Final account creation is blocked by policy.

## Run without live services

No key is needed to start the mock, use the operator page, or replay the hand-authored reference artifact:

```bash
uv run actionreplay serve
uv run actionreplay replay \
  --artifact examples/offline-balance.json \
  --inputs-file examples/member-b.json
```

`examples/offline-balance.json` is explicitly a **hand-authored test fixture**, not discovery evidence.

For reproducible offline record/replay evidence using a real browser and a scripted model double:

```bash
uv run python scripts/build_demo_evidence.py
```

This produces discovery-protocol, replay, not-found, simulated operator handoff, and transient-recovery examples under `/evidence/`. The scripted model is imported from tests only. The handoff example explicitly logs that a test harness simulates the operator.

## Failure outcomes and human handoff

Known business outcomes:

```bash
uv run actionreplay replay --artifact examples/offline-balance.json --inputs-file examples/member-missing.json
uv run actionreplay replay --artifact examples/offline-balance.json --inputs-file examples/member-invalid.json
```

These return `business_outcome`, with `MEMBER_NOT_FOUND` or `INVALID_MEMBER_ID`, rather than crashing.

To demonstrate session expiry, stop the server and restart:

```bash
uv run actionreplay serve --scenario session
uv run actionreplay replay --artifact examples/offline-balance.json --inputs-file examples/member-a.json
```

1. Open the operator URL printed by `serve`.
2. Wait for `SESSION_EXPIRED`, then select **Take Control**.
3. In the existing Chromium window, click **Restore session**.
4. Return to the operator page and select **Resume**.

The same tab, context, and cookies remain alive. Automation cannot act while ownership is `HUMAN`. Resume checks the interrupted step's precondition/postcondition; an incompatible state stays paused. Manual actions are logged with values redacted and never silently incorporated into the artifact.

Other scenarios: `permission`, `slow`, `transient`, `interstitial`, and `dialog`. Use `--scenario dialog` to exercise an unknown HTML dialog, resolve it in the same browser, and resume. Native JavaScript dialogs can be dismissed explicitly through the operator page while the human owns the session. `--headless` is suitable for automated tests, not interactive local takeover.

## Configuration and execution bounds

Defaults are in `config.example.yaml`. Precedence is defaults → config file → explicit CLI options. The server owns the configuration; discovery CLI options override its step/time limits for that run.

- `discovery.max_steps`: **30 by default, configurable**, including malformed/rejected model decisions.
- `discovery.max_duration_seconds`: 300, excluding human intervention time.
- `discovery.max_consecutive_no_progress`: 3.
- `execution.action_timeout_seconds`: 10.
- `execution.max_recovery_attempts`: 2, including known interstitial handlers.
- `handoff.timeout_seconds`: 900.
- `evidence.retention_days`: 7.

When a discovery budget is exhausted, Take Control and provide positive step **and** time extensions before Resume. Each exhausted-budget intervention requires a new explicit extension. Resume never resets counters silently. Abort and handoff expiry return structured failures.

The trusted policy configuration contains allowed routes, action types, click identities, field identities, approved artifact literals, and stable attributes. Adapt these explicitly for a new target. Unknown controls are blocked; an artifact cannot grant itself permission. The startup heading checks the configured application/version marker.

## Artifacts and evidence

`schemas/capability.schema.json` is exported from Pydantic; regenerate with:

```bash
uv run actionreplay schema
```

Artifacts contain typed inputs/outputs, frame-scoped targets, ordered actions, parameter/variable bindings, checkpoints, and deterministic outcomes. Loading rejects unsupported versions, unknown fields/actions, invalid references, duplicate steps, and variables used before extraction. Capabilities use immutable revisions.

Each `runs/<run-id>/` contains:

- `manifest.json`: lifecycle, versions, provenance, effective limits, capability hash.
- `events.jsonl`: ordered actions, policy checks, checkpoints, retries, interventions, ownership changes, model usage metadata.
- `capability.json`: the exact recorded/executed revision.
- `result.json`: terminal outcome and redacted output summary.
- `snapshots/`: sanitized structural failure/intervention evidence.

Screenshots are transient model inputs. No raw screenshots, HTML dumps, model transcripts, browser traces, cookies, credentials, or extracted financial values are persisted. This is a synthetic demonstration, not a universal PII classifier. See REPORT.md for the boundaries.

Export selected completed runs after the live demonstration:

```bash
uv run actionreplay export-evidence DISCOVERY_RUN_ID REPLAY_RUN_ID OUTCOME_RUN_ID HANDOFF_RUN_ID
```

Optionally use `--canaries-file path/to/local-canaries.json` containing a JSON array of strings. Never commit that file if it contains real sensitive values. Export runs a secret/canary scan and generates an index. A scan supplements structural redaction; it is not a proof that arbitrary real-world data is safe.

```bash
uv run actionreplay cleanup
```

Cleanup removes only finished run directories older than the retention period. It preserves incomplete/active runs, capabilities, and exported evidence. A crash leaves the manifest visibly unfinished; no automatic crash resume is claimed. Evidence-write failure stops automation.

## Verification and submission

```bash
uv run pytest -q
uv run ruff check actionreplay tests scripts
```

Tests launch local servers and Chromium. They need permission to bind loopback ports and launch a browser. Integration tests cover replay with model access prohibited, alternate inputs, errors, handoff, recording, configuration, and evidence redaction. See `IMPLEMENTATION.md` for coverage and outstanding live verification.

Before submission, generate genuine OpenRouter evidence, review the public files for secrets, and follow the assignment's publication/submission instructions. No repository has been published and no email has been sent by this implementation task.
