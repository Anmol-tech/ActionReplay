# Evidence index

Provenance is explicit. Offline fixtures are not genuine discovery evidence.

## Look here first (current LegacyBank mock)

- [abf58aa2f2b84125b970a6bf936fa4b4](abf58aa2f2b84125b970a6bf936fa4b4/manifest.json) — discovery, live, scenario `default`, result `OK` — current-mock live discovery. [Events](abf58aa2f2b84125b970a6bf936fa4b4/events.jsonl), [capability](abf58aa2f2b84125b970a6bf936fa4b4/capability.json).
- [ba89a1c3d5b1478786b3ecb17a61d61a](ba89a1c3d5b1478786b3ecb17a61d61a/manifest.json) — replay, live, scenario `default`, result `OK` — alternate-input replay. [Events](ba89a1c3d5b1478786b3ecb17a61d61a/events.jsonl), [capability](ba89a1c3d5b1478786b3ecb17a61d61a/capability.json).
- [f32d4a63d2f5401ebe239deff4d156c5](f32d4a63d2f5401ebe239deff4d156c5/manifest.json) — replay, live, scenario `default`, result `MEMBER_NOT_FOUND` — MEMBER_NOT_FOUND business outcome. [Events](f32d4a63d2f5401ebe239deff4d156c5/events.jsonl), [capability](f32d4a63d2f5401ebe239deff4d156c5/capability.json).

## Stretch demos

- [cd63627f621c45cca360f31a03240a3f](cd63627f621c45cca360f31a03240a3f/manifest.json) — replay, live, scenario `drift`, stretch `assisted_fallback`, result `OK` — one policy-checked assist click on label drift. [Events](cd63627f621c45cca360f31a03240a3f/events.jsonl), [capability](cd63627f621c45cca360f31a03240a3f/capability.json).
- [8763b94caf4c43ff8a5c7975f841fb29](8763b94caf4c43ff8a5c7975f841fb29/manifest.json) — replay, offline-artifact-real-browser, scenario `confirm-handoff`, stretch `confirm_handoff_video`, result `OK` — Confirm* Take Control → click Confirm → Resume (same session). [Events](8763b94caf4c43ff8a5c7975f841fb29/events.jsonl), [video](8763b94caf4c43ff8a5c7975f841fb29/confirm-handoff.webm).
- [stability.md](stability.md) — stretch multi-run stability: N deterministic replays of savings-balance with pass rate.

## Archive / offline fixtures

- [06ea56e6273640d1963aa29234eaa760](06ea56e6273640d1963aa29234eaa760/manifest.json) — replay, offline-artifact-real-browser, scenario `normal`, result `MEMBER_NOT_FOUND`. [Events](06ea56e6273640d1963aa29234eaa760/events.jsonl), [capability](06ea56e6273640d1963aa29234eaa760/capability.json).
- [17df00c3bcbd49acb68a8290b58f0746](17df00c3bcbd49acb68a8290b58f0746/manifest.json) — replay, offline-artifact-real-browser, scenario `normal`, result `OK`. [Events](17df00c3bcbd49acb68a8290b58f0746/events.jsonl), [capability](17df00c3bcbd49acb68a8290b58f0746/capability.json).
- [1a3caae3010a429c9082ca2a6509141f](1a3caae3010a429c9082ca2a6509141f/manifest.json) — replay, live, scenario `default`, result `MEMBER_NOT_FOUND`. [Events](1a3caae3010a429c9082ca2a6509141f/events.jsonl), [capability](1a3caae3010a429c9082ca2a6509141f/capability.json).
- [57bfe9b54b07485cbaa080e8d9465989](57bfe9b54b07485cbaa080e8d9465989/manifest.json) — discovery, offline-scripted-model, scenario `normal`, result `OK`. [Events](57bfe9b54b07485cbaa080e8d9465989/events.jsonl), [capability](57bfe9b54b07485cbaa080e8d9465989/capability.json).
- [58980d9f11614b41ad16e6c441636b3b](58980d9f11614b41ad16e6c441636b3b/manifest.json) — replay, offline-artifact-real-browser, scenario `transient`, result `OK`. [Events](58980d9f11614b41ad16e6c441636b3b/events.jsonl), [capability](58980d9f11614b41ad16e6c441636b3b/capability.json).
- [755f7eba08044d5788225e703fca8337](755f7eba08044d5788225e703fca8337/manifest.json) — replay, live, scenario `default`, result `OK`. [Events](755f7eba08044d5788225e703fca8337/events.jsonl), [capability](755f7eba08044d5788225e703fca8337/capability.json).
- [7ad50bfbfbc443c49874a1e0bb7e76e2](7ad50bfbfbc443c49874a1e0bb7e76e2/manifest.json) — discovery, live, scenario `default`, result `OK`. [Events](7ad50bfbfbc443c49874a1e0bb7e76e2/events.jsonl), [capability](7ad50bfbfbc443c49874a1e0bb7e76e2/capability.json).
- [9b39dd1759ce42bc88477d89f3961a1e](9b39dd1759ce42bc88477d89f3961a1e/manifest.json) — replay, live, scenario `default`, result `MEMBER_NOT_FOUND`. [Events](9b39dd1759ce42bc88477d89f3961a1e/events.jsonl), [capability](9b39dd1759ce42bc88477d89f3961a1e/capability.json).
- [c7bc81d0839445468937c5f40f00a111](c7bc81d0839445468937c5f40f00a111/manifest.json) — replay, live, scenario `default`, result `OK`. [Events](c7bc81d0839445468937c5f40f00a111/events.jsonl), [capability](c7bc81d0839445468937c5f40f00a111/capability.json).
- [d9a1c7ad405845c3a369f7580170a0dc](d9a1c7ad405845c3a369f7580170a0dc/manifest.json) — replay, offline-artifact-real-browser, scenario `session`, result `OK`. [Events](d9a1c7ad405845c3a369f7580170a0dc/events.jsonl), [capability](d9a1c7ad405845c3a369f7580170a0dc/capability.json).
