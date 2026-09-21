# Submission

Public repository:

```
https://github.com/Anmol-tech/ActionReplay
```

## Email (copy/paste)

**To:** assignments@interface.ai  
**Subject:** ActionReplay submission — Anmol

```
https://github.com/Anmol-tech/ActionReplay
```

Use the address you applied with. Do not attach a zip.

## What to click first in the repo

1. [`README.md`](README.md) — reviewer path at the top  
2. [`evidence/index.md`](evidence/index.md) — **Look here first** (live trio), then stretch (assist / Confirm video / stability)  
3. [`REPORT.md`](REPORT.md) — design trade-offs  

## Optional local demos

```bash
uv run actionreplay serve
uv run actionreplay replay --artifact examples/offline-balance.json --inputs-file examples/member-b.json
uv run python scripts/demo_catalog_invoke.py      # GET /capabilities → POST /runs by name
uv run python scripts/build_assist_evidence.py    # needs OpenRouter; regenerates drift assist evidence
uv run python scripts/record_confirm_handoff.py   # Confirm* handoff + .webm
uv run python scripts/stability_report.py         # multi-run stability → evidence/stability.md
```
