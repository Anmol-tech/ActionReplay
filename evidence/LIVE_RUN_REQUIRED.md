# Genuine discovery evidence

The live OpenRouter discovery requirement is satisfied by:

- [7ad50bfbfbc443c49874a1e0bb7e76e2](7ad50bfbfbc443c49874a1e0bb7e76e2/manifest.json) — discovery, `provenance: live`, model `qwen/qwen3-vl-235b-a22b-instruct`, result `OK`
- [c7bc81d0839445468937c5f40f00a111](c7bc81d0839445468937c5f40f00a111/manifest.json) — replay of the saved capability on the **current** LegacyBank mock with alternate member inputs, result `OK`
- [9b39dd1759ce42bc88477d89f3961a1e](9b39dd1759ce42bc88477d89f3961a1e/manifest.json) — replay business outcome `MEMBER_NOT_FOUND` on the current mock

Refresh current-mock replays with:

```bash
uv run python scripts/refresh_live_evidence.py
```

Optional new discovery (requires a successful OpenRouter run):

```bash
uv run python scripts/refresh_live_evidence.py --discover
```

Offline scripted-model runs remain in this directory for handoff/transient demonstrations. They are labeled as such and are not substitutes for the live discovery run above.
