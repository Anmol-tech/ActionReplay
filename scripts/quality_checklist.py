"""One-shot discovery quality checklist against the live LegacyBank mock.

Requires: `uv run actionreplay serve` already running (mock on :8000)
and OPENROUTER_* in .env.

  uv run python scripts/quality_checklist.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from actionreplay.cli import load_local_env
from actionreplay.config import Config
from actionreplay.discovery import DiscoveryEngine, OpenRouterClient
from actionreplay.evidence import EvidenceWriter
from actionreplay.models import Capability
from actionreplay.replay import ReplayEngine
from actionreplay.session import SessionController
from actionreplay.surface import BrowserSurface


ROOT = Path(__file__).resolve().parents[1]
TARGET = "http://127.0.0.1:8000"
CAP_ROOT = ROOT / "runs" / "quality-capabilities"
RUNS = ROOT / "runs" / "quality-checklist"


async def runtime(mode: str):
    load_local_env()
    config = Config(headless=True)
    config.policy.base_url = TARGET
    config.evidence.directory = RUNS
    config.discovery.max_steps = 40
    config.discovery.max_duration_seconds = 240
    writer = EvidenceWriter(
        config.evidence.directory,
        mode,
        config.model_dump(mode="json"),
        sensitive=["00123", "00678", "00000", "00456", "Alex Rivera", "25.00"],
        provenance="live",
    )
    controller = SessionController(writer, 90)
    surface = BrowserSurface(config, writer, lambda: controller.owner)
    controller.surface = surface
    await surface.start()
    return config, writer, controller, surface


async def discover(goal: str, inputs: dict, name: str):
    config, writer, controller, surface = await runtime("discovery")
    client = OpenRouterClient()
    try:
        result = await DiscoveryEngine(config, surface, writer, controller, client).run(
            goal, TARGET, inputs, name, CAP_ROOT
        )
        artifact_path = None
        folder = CAP_ROOT / name
        if folder.is_dir():
            revs = sorted(int(p.stem) for p in folder.glob("*.json") if p.stem.isdigit())
            if revs:
                artifact_path = folder / f"{revs[-1]}.json"
        hardcodes = []
        if artifact_path and artifact_path.is_file():
            text = artifact_path.read_text()
            for needle in ("00123", "00678", "00456"):
                if needle in text:
                    hardcodes.append(needle)
        return {
            "kind": "discovery",
            "name": name,
            "goal": goal,
            "run_id": writer.run_id,
            "status": result.status,
            "code": result.code,
            "outputs": result.outputs,
            "artifact": str(artifact_path.relative_to(ROOT)) if artifact_path else None,
            "hardcoded_ids": hardcodes,
            "ok": result.status == "success" and result.code == "OK" and not hardcodes,
        }
    finally:
        await client.close()
        await surface.close()


async def replay(artifact_path: Path, inputs: dict, expect_code: str):
    artifact = Capability.model_validate_json(artifact_path.read_text())
    config, writer, controller, surface = await runtime("replay")
    try:
        result = await ReplayEngine(config, surface, writer, controller).run(artifact, inputs)
        ok = result.code == expect_code
        if expect_code == "OK":
            ok = ok and result.status == "success"
        else:
            ok = ok and result.status == "business_outcome"
        return {
            "kind": "replay",
            "artifact": str(artifact_path.relative_to(ROOT)),
            "inputs": inputs,
            "expect": expect_code,
            "run_id": writer.run_id,
            "status": result.status,
            "code": result.code,
            "outputs": result.outputs,
            "ok": ok,
        }
    finally:
        await surface.close()


async def main():
    load_local_env()
    if not (os.getenv("OPENROUTER_API_KEY") and os.getenv("OPENROUTER_MODEL")):
        raise SystemExit("OPENROUTER_API_KEY and OPENROUTER_MODEL required")

    # Quick mock reachability
    import httpx

    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(TARGET, timeout=3.0)
            if r.status_code >= 500:
                raise SystemExit(f"Mock unhealthy at {TARGET}")
    except httpx.HTTPError as exc:
        raise SystemExit(f"Start the mock first: uv run actionreplay serve\n({exc})") from exc

    results = []

    # 1) Baseline savings
    d1 = await discover(
        "Find the savings balance for the supplied member",
        {"member_id": "00123"},
        "quality-savings",
    )
    results.append(d1)
    print(json.dumps(d1))

    if d1.get("artifact"):
        art = ROOT / d1["artifact"]
        r_ok = await replay(art, {"member_id": "00678"}, "OK")
        results.append(r_ok)
        print(json.dumps(r_ok))
        r_nf = await replay(art, {"member_id": "00000"}, "MEMBER_NOT_FOUND")
        results.append(r_nf)
        print(json.dumps(r_nf))

    # 2) Alternate wording
    d2 = await discover(
        "Look up the supplied member_id and read their current savings balance",
        {"member_id": "00123"},
        "quality-savings-alt",
    )
    results.append(d2)
    print(json.dumps(d2))

    # 3) Transfer review (do not confirm)
    d3 = await discover(
        "Prepare a funds transfer for the supplied member using from_account and amount. "
        "Stop on the transfer review screen and return the displayed amount. Do not confirm the transfer.",
        {"member_id": "00123", "from_account": "Savings", "amount": "25.00"},
        "quality-transfer-review",
    )
    results.append(d3)
    print(json.dumps(d3))

    # 4) Create member review
    d4 = await discover(
        "Prepare creating a new member using new_member_id and display_name. "
        "Stop on the create-member review screen and return the displayed new member ID. Do not confirm create.",
        {"new_member_id": "00456", "display_name": "Alex Rivera"},
        "quality-create-review",
    )
    results.append(d4)
    print(json.dumps(d4))

    passed = sum(1 for r in results if r.get("ok"))
    summary = {
        "passed": passed,
        "total": len(results),
        "pass_rate_pct": round(100.0 * passed / len(results), 1) if results else 0,
        "results": results,
    }
    out = ROOT / "runs" / "quality-checklist-summary.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({"summary": {"passed": passed, "total": len(results), "report": str(out)}}))
    raise SystemExit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    asyncio.run(main())
