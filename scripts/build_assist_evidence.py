"""Build assisted-fallback evidence on the drift scenario.

Uses a real OpenRouter client for one policy-checked recovery step when the
recorded "Review transfer" control is missing (label drifted to Continue to review).

  uv run python scripts/build_assist_evidence.py
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from actionreplay.assist import AssistedFallback
from actionreplay.cli import load_local_env
from actionreplay.config import Config
from actionreplay.discovery import OpenRouterClient
from actionreplay.evidence import EvidenceWriter, export_runs
from actionreplay.replay import ReplayEngine
from actionreplay.session import SessionController
from actionreplay.surface import BrowserSurface
from tests.helpers import transfer_review_capability


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
        env=dict(os.environ, ACTIONREPLAY_SCENARIO="drift"),
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


async def main():
    load_local_env()
    if not (os.getenv("OPENROUTER_API_KEY") and os.getenv("OPENROUTER_MODEL")):
        raise SystemExit("OPENROUTER_API_KEY and OPENROUTER_MODEL required")

    process, url = await serve_mock()
    try:
        config = Config(headless=True, scenario="drift")
        config.policy.base_url = url
        config.execution.assisted_fallback = True
        config.execution.assisted_fallback_max_per_run = 1
        config.evidence.directory = Path("runs/assist-evidence")
        writer = EvidenceWriter(
            config.evidence.directory,
            "replay",
            config.model_dump(mode="json"),
            sensitive=["00123", "25.00"],
            provenance="live",
        )
        writer.manifest["scenario"] = "drift"
        writer.manifest["stretch"] = "assisted_fallback"
        writer.write("manifest.json", writer.manifest)
        controller = SessionController(writer, 120)
        surface = BrowserSurface(config, writer, lambda: controller.owner)
        controller.surface = surface
        await surface.start()
        try:
            client = OpenRouterClient()
            assist = AssistedFallback(config, surface, writer, client)
            artifact = transfer_review_capability()
            writer.attach(artifact)
            result = await ReplayEngine(config, surface, writer, controller, assist=assist).run(
                artifact, {"member_id": "00123"}
            )
            print(json.dumps({"run_id": writer.run_id, "code": result.code, "status": result.status}))
            events = (writer.path / "events.jsonl").read_text()
            if "assisted_fallback" not in events and "step_completed_by_assist" not in events:
                raise RuntimeError("Expected assisted_fallback evidence events")
            if result.code != "OK":
                raise RuntimeError(f"Assist evidence run failed: {result.code}")
            export_runs(
                config.evidence.directory,
                Path("evidence"),
                [writer.run_id],
                sensitive=["00123", "25.00"],
            )
            print(json.dumps({"exported": writer.run_id}))
        finally:
            await surface.close()
            await client.close()
    finally:
        process.terminate()
        process.wait(timeout=10)


if __name__ == "__main__":
    asyncio.run(main())
