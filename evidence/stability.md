# Multi-run stability

Artifact: `capabilities/savings-balance/2.json` (`savings-balance` rev 2)
Inputs: `examples/member-b.json`
Attempts: **5** · Passes: **5** · Pass rate: **100%**

| # | run_id | status | code |
|---|---|---|---|
| 1 | `b5e493922fc84d2c9256a738432bfa91` | success | `OK` |
| 2 | `4c0bfa00b52a49dca4a0eab2553d56b3` | success | `OK` |
| 3 | `4ee51bd0938a48c0b710006f9277a2ba` | success | `OK` |
| 4 | `af4c9e9d1d2e4824a82f33c6e5146130` | success | `OK` |
| 5 | `12d4cc4559ca4d91ab3d4a720499a007` | success | `OK` |

This stretch reports a flakiness signal for deterministic replay. It does not gate draft→approved promotion (that remains a deliberate cut).
