# Evidence index

Provenance is explicit. Prefer the `live` discovery/replay entries for the assignment demonstration; offline fixtures remain for handoff/transient paths.

## Live OpenRouter demonstration

- [abf58aa2f2b84125b970a6bf936fa4b4](abf58aa2f2b84125b970a6bf936fa4b4/manifest.json) — discovery on the **current** LegacyBank mock, live OpenRouter, result `OK`. [Events](abf58aa2f2b84125b970a6bf936fa4b4/events.jsonl), [capability](abf58aa2f2b84125b970a6bf936fa4b4/capability.json).
- [ba89a1c3d5b1478786b3ecb17a61d61a](ba89a1c3d5b1478786b3ecb17a61d61a/manifest.json) — replay, alternate inputs, result `OK`. [Events](ba89a1c3d5b1478786b3ecb17a61d61a/events.jsonl), [capability](ba89a1c3d5b1478786b3ecb17a61d61a/capability.json).
- [f32d4a63d2f5401ebe239deff4d156c5](f32d4a63d2f5401ebe239deff4d156c5/manifest.json) — replay, result `MEMBER_NOT_FOUND`. [Events](f32d4a63d2f5401ebe239deff4d156c5/events.jsonl), [capability](f32d4a63d2f5401ebe239deff4d156c5/capability.json).

Older live runs (`7ad50bfb…`, `c7bc81d0…`, `9b39dd17…`, and earlier) remain for history; prefer the trio above for review.

## Offline / fixture demonstrations

- [06ea56e6273640d1963aa29234eaa760](06ea56e6273640d1963aa29234eaa760/manifest.json) — replay, offline-artifact-real-browser, scenario `normal`, result `MEMBER_NOT_FOUND`. [Events](06ea56e6273640d1963aa29234eaa760/events.jsonl), [capability](06ea56e6273640d1963aa29234eaa760/capability.json).
- [17df00c3bcbd49acb68a8290b58f0746](17df00c3bcbd49acb68a8290b58f0746/manifest.json) — replay, offline-artifact-real-browser, scenario `normal`, result `OK`. [Events](17df00c3bcbd49acb68a8290b58f0746/events.jsonl), [capability](17df00c3bcbd49acb68a8290b58f0746/capability.json).
- [57bfe9b54b07485cbaa080e8d9465989](57bfe9b54b07485cbaa080e8d9465989/manifest.json) — discovery, offline-scripted-model, scenario `normal`, result `OK`. [Events](57bfe9b54b07485cbaa080e8d9465989/events.jsonl), [capability](57bfe9b54b07485cbaa080e8d9465989/capability.json).
- [58980d9f11614b41ad16e6c441636b3b](58980d9f11614b41ad16e6c441636b3b/manifest.json) — replay, offline-artifact-real-browser, scenario `transient`, result `OK`. [Events](58980d9f11614b41ad16e6c441636b3b/events.jsonl), [capability](58980d9f11614b41ad16e6c441636b3b/capability.json).
- [d9a1c7ad405845c3a369f7580170a0dc](d9a1c7ad405845c3a369f7580170a0dc/manifest.json) — replay, offline-artifact-real-browser, scenario `session`, result `OK`. [Events](d9a1c7ad405845c3a369f7580170a0dc/events.jsonl), [capability](d9a1c7ad405845c3a369f7580170a0dc/capability.json).
