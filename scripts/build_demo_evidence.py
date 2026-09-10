"""Reproducible OFFLINE evidence on real Chromium. Never claims live model provenance.

Run from the repository root with: uv run python scripts/build_demo_evidence.py
"""

import asyncio
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import httpx

# This script intentionally uses the labeled test double, never production discovery.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from actionreplay.config import Config
from actionreplay.discovery import DiscoveryEngine
from actionreplay.evidence import EvidenceWriter, export_runs
from actionreplay.models import Capability
from actionreplay.replay import ReplayEngine
from actionreplay.session import SessionController
from actionreplay.surface import BrowserSurface
from tests.test_discovery import FixtureModel


async def serve_mock(scenario):
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
        env=dict(os.environ, ACTIONREPLAY_SCENARIO=scenario),
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


async def run(scenario, member, artifact=None):
    process, url = await serve_mock(scenario)
    config = Config(headless=True)
    config.policy.base_url = url
    config.evidence.directory = Path("runs/offline-demo")
    writer = EvidenceWriter(
        config.evidence.directory,
        "replay" if artifact else "discovery",
        config.model_dump(mode="json"),
        sensitive=["00123", "00678", "00000"],
        provenance="offline-scripted-model" if not artifact else "offline-artifact-real-browser",
    )
    writer.manifest["scenario"] = scenario
    writer.write("manifest.json", writer.manifest)
    controller = SessionController(writer, 30)
    surface = BrowserSurface(config, writer, lambda: controller.owner)
    controller.surface = surface
    try:
        await surface.start()
        if artifact:
            task = asyncio.create_task(
                ReplayEngine(config, surface, writer, controller).run(artifact, {"member_id": member})
            )
            if scenario == "session":
                for _ in range(400):
                    if controller.intervention:
                        break
                    if task.done():
                        raise RuntimeError("Run ended before handoff")
                    await asyncio.sleep(0.025)
                intervention = controller.intervention
                if intervention is None:
                    raise RuntimeError("No intervention")
                controller.take_control(intervention.id)
                writer.event(
                    "operator_simulation",
                    owner="HUMAN",
                    explanation="Test harness simulates the operator on the existing browser",
                )
                await surface.page.frame(name="workspace").get_by_role("link", name="Restore session").click()
                controller.resume(intervention.id)
            result = await task
        else:
            result = await DiscoveryEngine(config, surface, writer, controller, FixtureModel()).run(
                "Read the supplied member's savings balance",
                url,
                {"member_id": member},
                "offline-recorded-balance",
                Path("runs/offline-capabilities"),
            )
        print(
            json.dumps(
                {"run_id": writer.run_id, "scenario": scenario, "status": result.status, "code": result.code}
            )
        )
        if result.status == "failure":
            raise RuntimeError("Offline demo failed: " + result.code)
        export_runs(
            config.evidence.directory,
            Path("evidence"),
            [writer.run_id],
            sensitive=["00123", "00678", "00000", "1250.45", "9876.54"],
        )
        return Capability.model_validate_json((writer.path / "capability.json").read_text())
    finally:
        await surface.close()
        process.terminate()
        process.wait(timeout=10)


async def main():
    artifact = await run("normal", "00123")
    for scenario, member in [
        ("normal", "00678"),
        ("normal", "00000"),
        ("session", "00123"),
        ("transient", "00123"),
    ]:
        await run(scenario, member, artifact)


if __name__ == "__main__":
    asyncio.run(main())
