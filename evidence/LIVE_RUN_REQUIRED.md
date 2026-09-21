# Genuine discovery evidence

Prefer **Look here first** in [`index.md`](index.md). Primary run IDs live in [`primary.json`](primary.json).

Current-mock live OpenRouter demonstration:

- [abf58aa2f2b84125b970a6bf936fa4b4](abf58aa2f2b84125b970a6bf936fa4b4/manifest.json) — discovery, `provenance: live`, result `OK`
- [ba89a1c3d5b1478786b3ecb17a61d61a](ba89a1c3d5b1478786b3ecb17a61d61a/manifest.json) — replay with alternate member inputs, result `OK`
- [f32d4a63d2f5401ebe239deff4d156c5](f32d4a63d2f5401ebe239deff4d156c5/manifest.json) — replay business outcome `MEMBER_NOT_FOUND`

Refresh with:

```bash
uv run python scripts/refresh_live_evidence.py --discover
```

Stretch regenerators:

```bash
uv run python scripts/build_assist_evidence.py
uv run python scripts/record_confirm_handoff.py
uv run python scripts/stability_report.py
```

Offline scripted-model runs remain in this directory for older handoff/transient demonstrations. They are labeled as such and are not substitutes for the live discovery run above.
