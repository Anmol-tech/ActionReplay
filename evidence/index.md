# Evidence index

Provenance is explicit. Prefer the `live` discovery/replay entries for the assignment demonstration; offline fixtures remain for handoff/transient paths.

## Live OpenRouter demonstration

- [7ad50bfbfbc443c49874a1e0bb7e76e2](7ad50bfbfbc443c49874a1e0bb7e76e2/manifest.json) — discovery, live, result `OK` (genuine OpenRouter run). [Events](7ad50bfbfbc443c49874a1e0bb7e76e2/events.jsonl), [capability](7ad50bfbfbc443c49874a1e0bb7e76e2/capability.json).
- [c7bc81d0839445468937c5f40f00a111](c7bc81d0839445468937c5f40f00a111/manifest.json) — replay on the **current** LegacyBank mock, alternate inputs, result `OK`. [Events](c7bc81d0839445468937c5f40f00a111/events.jsonl), [capability](c7bc81d0839445468937c5f40f00a111/capability.json).
- [9b39dd1759ce42bc88477d89f3961a1e](9b39dd1759ce42bc88477d89f3961a1e/manifest.json) — replay on the current mock, result `MEMBER_NOT_FOUND`. [Events](9b39dd1759ce42bc88477d89f3961a1e/events.jsonl), [capability](9b39dd1759ce42bc88477d89f3961a1e/capability.json).

Older live replays (`755f7eba…`, `1a3caae3…`) remain in this directory for history; prefer the current-mock pair above for review.

## Offline / fixture demonstrations

- [06ea56e6273640d1963aa29234eaa760](06ea56e6273640d1963aa29234eaa760/manifest.json) — replay, offline-artifact-real-browser, scenario `normal`, result `MEMBER_NOT_FOUND`. [Events](06ea56e6273640d1963aa29234eaa760/events.jsonl), [capability](06ea56e6273640d1963aa29234eaa760/capability.json).
- [17df00c3bcbd49acb68a8290b58f0746](17df00c3bcbd49acb68a8290b58f0746/manifest.json) — replay, offline-artifact-real-browser, scenario `normal`, result `OK`. [Events](17df00c3bcbd49acb68a8290b58f0746/events.jsonl), [capability](17df00c3bcbd49acb68a8290b58f0746/capability.json).
- [57bfe9b54b07485cbaa080e8d9465989](57bfe9b54b07485cbaa080e8d9465989/manifest.json) — discovery, offline-scripted-model, scenario `normal`, result `OK`. [Events](57bfe9b54b07485cbaa080e8d9465989/events.jsonl), [capability](57bfe9b54b07485cbaa080e8d9465989/capability.json).
- [58980d9f11614b41ad16e6c441636b3b](58980d9f11614b41ad16e6c441636b3b/manifest.json) — replay, offline-artifact-real-browser, scenario `transient`, result `OK`. [Events](58980d9f11614b41ad16e6c441636b3b/events.jsonl), [capability](58980d9f11614b41ad16e6c441636b3b/capability.json).
- [d9a1c7ad405845c3a369f7580170a0dc](d9a1c7ad405845c3a369f7580170a0dc/manifest.json) — replay, offline-artifact-real-browser, scenario `session`, result `OK`. [Events](d9a1c7ad405845c3a369f7580170a0dc/events.jsonl), [capability](d9a1c7ad405845c3a369f7580170a0dc/capability.json).
