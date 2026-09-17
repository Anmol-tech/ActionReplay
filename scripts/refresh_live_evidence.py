"""Refresh live evidence against the current mock bank.

Default: replay an existing savings-balance artifact (OK + MEMBER_NOT_FOUND) with
provenance=live — validates the current UI without another costly discovery.

Optional --discover runs a new OpenRouter discovery first (requires a successful model run).

  uv run python scripts/refresh_live_evidence.py
  uv run python scripts/refresh_live_evidence.py --discover
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from actionreplay.cli import load_local_env
from actionreplay.config import Config
from actionreplay.discovery import DiscoveryEngine, OpenRouterClient
from actionreplay.evidence import EvidenceWriter, export_runs
from actionreplay.models import Capability
from actionreplay.replay import ReplayEngine
from actionreplay.session import SessionController
from actionreplay.surface import BrowserSurface


def latest_savings_artifact() -> Capability:
    folder = Path("capabilities/savings-balance")
    revisions = sorted(
        (p for p in folder.glob("*.json") if p.stem.isdigit()),
        key=lambda p: int(p.stem),
    )
    if not revisions:
        raise SystemExit("No capabilities/savings-balance/*.json found")
    return Capability.model_validate_json(revisions[-1].read_text())


async def serve_mock():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "actionreplay.mock_app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--no-access-log",
            "--log-level",
            "error",
        ],
        env=dict(os.environ, ACTIONREPLAY_SCENARIO="normal"),
    )
    url = f"http://127.0.0.1:{port}"
    async with httpx.AsyncClient() as client:
        for _ in range(100):
            try:
                if (await client.get(url)).status_code == 200:
                    return process, url
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.05)
    process.terminate()
    raise RuntimeError("Mock failed to start")


async def with_runtime(mode: str, url: str, handoff_timeout: float = 60):
    config = Config(headless=True)
    config.policy.base_url = url
    config.evidence.directory = Path("runs/live-refresh")
    config.discovery.max_steps = 40
    config.handoff.timeout_seconds = handoff_timeout
    writer = EvidenceWriter(
        config.evidence.directory,
        mode,
        config.model_dump(mode="json"),
        sensitive=["00123", "00678", "00000", "1250.45", "9876.54"],
        provenance="live",
    )
    writer.write("manifest.json", writer.manifest)
    controller = SessionController(writer, handoff_timeout)
    surface = BrowserSurface(config, writer, lambda: controller.owner)
    controller.surface = surface
    await surface.start()
    return config, writer, controller, surface


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--discover", action="store_true")
    args = parser.parse_args()

    load_local_env()
    process, url = await serve_mock()
    run_ids = []
    try:
        artifact = None
        if args.discover:
            if not (os.getenv("OPENROUTER_API_KEY") and os.getenv("OPENROUTER_MODEL")):
                raise SystemExit("OPENROUTER_API_KEY and OPENROUTER_MODEL required for --discover")
            config, writer, controller, surface = await with_runtime("discovery", url, handoff_timeout=90)
            try:
                client = OpenRouterClient()
                result = await DiscoveryEngine(config, surface, writer, controller, client).run(
                    "Find the savings balance for the supplied member",
                    url,
                    {"member_id": "00123"},
                    "savings-balance",
                    Path("capabilities"),
                )
                print(json.dumps({"phase": "discovery", "run_id": writer.run_id, "code": result.code}))
                if result.code != "OK":
                    raise RuntimeError(f"Discovery failed: {result.code}")
                run_ids.append(writer.run_id)
                artifact = Capability.model_validate_json((writer.path / "capability.json").read_text())
            finally:
                await surface.close()
        else:
            artifact = latest_savings_artifact()
            print(json.dumps({"phase": "artifact", "capability": artifact.capability_id, "revision": artifact.revision}))

        for member, expected in [("00678", "OK"), ("00000", "MEMBER_NOT_FOUND")]:
            config, writer, controller, surface = await with_runtime("replay", url)
            try:
                result = await ReplayEngine(config, surface, writer, controller).run(
                    artifact, {"member_id": member}
                )
                print(
                    json.dumps(
                        {
                            "phase": "replay",
                            "member": member,
                            "run_id": writer.run_id,
                            "code": result.code,
                        }
                    )
                )
                if result.code != expected:
                    raise RuntimeError(f"Replay expected {expected}, got {result.code}")
                run_ids.append(writer.run_id)
            finally:
                await surface.close()

        export_runs(
            Path("runs/live-refresh"),
            Path("evidence"),
            run_ids,
            sensitive=["00123", "00678", "00000", "1250.45", "9876.54"],
        )
        print(json.dumps({"exported": run_ids}))
    finally:
        process.terminate()
        process.wait(timeout=10)


if __name__ == "__main__":
    asyncio.run(main())
