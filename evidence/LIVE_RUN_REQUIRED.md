# Genuine discovery evidence

The live OpenRouter discovery requirement is satisfied by:

- [abf58aa2f2b84125b970a6bf936fa4b4](abf58aa2f2b84125b970a6bf936fa4b4/manifest.json) — discovery on the **current** LegacyBank mock, `provenance: live`, result `OK`
- [ba89a1c3d5b1478786b3ecb17a61d61a](ba89a1c3d5b1478786b3ecb17a61d61a/manifest.json) — replay with alternate member inputs, result `OK`
- [f32d4a63d2f5401ebe239deff4d156c5](f32d4a63d2f5401ebe239deff4d156c5/manifest.json) — replay business outcome `MEMBER_NOT_FOUND`

Refresh with:

```bash
uv run python scripts/refresh_live_evidence.py --discover
```

Offline scripted-model runs remain in this directory for handoff/transient demonstrations. They are labeled as such and are not substitutes for the live discovery run above.
