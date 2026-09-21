"""Agent-facing catalog demo: list capabilities → invoke by name with typed args.

Requires a running coordinator (`uv run actionreplay serve`).

  uv run python scripts/demo_catalog_invoke.py
  # or one-liners:
  # curl -s http://127.0.0.1:8001/capabilities | python -m json.tool
  # curl -s -X POST http://127.0.0.1:8001/runs -H 'Content-Type: application/json' \\
  #   -d '{"mode":"replay","capability_name":"offline-balance","inputs":{"member_id":"00678"}}'
"""

from __future__ import annotations

import json
import sys
import time

import httpx

BASE = "http://127.0.0.1:8001"


def main():
    with httpx.Client(base_url=BASE, timeout=60.0) as client:
        try:
            catalog = client.get("/capabilities").json()["capabilities"]
        except httpx.HTTPError as exc:
            raise SystemExit(
                f"Coordinator not reachable at {BASE}. Start with: uv run actionreplay serve\n({exc})"
            ) from exc

        print("=== GET /capabilities (agent catalog) ===")
        for entry in catalog:
            inputs = entry.get("inputs") or {}
            print(
                f"- {entry['capability_id']}@{entry.get('latest_revision')} "
                f"({entry.get('kind')}) inputs={list(inputs)} "
                f"outputs={list((entry.get('outputs') or {}))}"
            )

        # Prefer fixture so this demo needs no live discovery artifact.
        capability_id = "offline-balance"
        if not any(e["capability_id"] == capability_id for e in catalog):
            capability_id = catalog[0]["capability_id"] if catalog else None
        if not capability_id:
            raise SystemExit("Catalog is empty")

        payload = {
            "mode": "replay",
            "capability_name": capability_id,
            "inputs": {"member_id": "00678"},
        }
        print(f"\n=== POST /runs (invoke {capability_id} with typed args) ===")
        print(json.dumps(payload))
        started = client.post("/runs", json=payload)
        if started.status_code >= 400:
            raise SystemExit(f"Invoke failed: {started.status_code} {started.text}")
        run_id = started.json()["run_id"]
        print(f"run_id={run_id}")

        for _ in range(120):
            state = client.get(f"/runs/{run_id}").json()
            if state.get("result"):
                print("\n=== result ===")
                print(json.dumps(state["result"], indent=2))
                code = state["result"].get("code")
                sys.exit(0 if code in {"OK", "MEMBER_NOT_FOUND"} or state["result"].get("status") != "failure" else 1)
            time.sleep(0.25)
        raise SystemExit("Timed out waiting for run result")


if __name__ == "__main__":
    main()
