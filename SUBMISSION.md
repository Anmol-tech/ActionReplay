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
2. [`evidence/index.md`](evidence/index.md) — live discovery + replay + not-found (+ assisted fallback when present)  
3. [`REPORT.md`](REPORT.md) — design trade-offs  

## Optional local demos

```bash
uv run actionreplay serve
uv run actionreplay replay --artifact examples/offline-balance.json --inputs-file examples/member-b.json
uv run python scripts/build_assist_evidence.py   # needs OpenRouter; regenerates drift assist evidence
```
