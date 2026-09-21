"""Record Confirm* same-session handoff with Playwright video.

Demonstrates: pause on HUMAN_CONFIRMATION_REQUIRED → Take Control → click
Confirm create on the live bank page → Resume → automation continues.

  uv run python scripts/record_confirm_handoff.py

Writes events + confirm-handoff.webm under evidence/<run_id>/ and updates
evidence/primary.json + evidence/index.md.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from actionreplay.config import Config
from actionreplay.evidence import EvidenceWriter, write_evidence_index
from actionreplay.models import RunResult
from actionreplay.session import SessionController
from actionreplay.surface import BrowserSurface


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
        env=dict(os.environ, ACTIONREPLAY_SCENARIO="default"),
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
    root = Path(__file__).resolve().parents[1]
    evidence_root = root / "evidence"
    runs_root = root / "runs" / "confirm-handoff"
    video_tmp = runs_root / "_video"
    if video_tmp.exists():
        shutil.rmtree(video_tmp)

    process, url = await serve_mock()
    try:
        config = Config(headless=True)
        config.policy.base_url = url
        config.evidence.directory = runs_root
        writer = EvidenceWriter(
            config.evidence.directory,
            "replay",
            config.model_dump(mode="json"),
            sensitive=["00499", "Test"],
            provenance="offline-artifact-real-browser",
        )
        writer.manifest["scenario"] = "confirm-handoff"
        writer.manifest["stretch"] = "confirm_handoff_video"
        writer.write("manifest.json", writer.manifest)
        controller = SessionController(writer, 60)
        surface = BrowserSurface(config, writer, lambda: controller.owner)
        controller.surface = surface
        await surface.start(record_video_dir=video_tmp)

        # Land on irreversible Confirm create review (same path discovery would pause on).
        await surface.page.goto(f"{url}/create-review?new_member_id=00499&display_name=Test")
        await surface.page.get_by_role("button", name="Confirm create").wait_for()
        await asyncio.sleep(0.4)

        async def confirmation_completed():
            return surface.left_confirmation_review()

        pause_task = asyncio.create_task(
            controller.pause("HUMAN_CONFIRMATION_REQUIRED", validator=confirmation_completed)
        )
        for _ in range(100):
            if controller.intervention is not None:
                break
            await asyncio.sleep(0.025)
        intervention = controller.intervention
        if intervention is None:
            raise RuntimeError("No confirmation intervention")

        # Simulated operator on the SAME browser/context (assignment-allowed).
        controller.take_control(intervention.id)
        writer.event(
            "operator_simulation",
            owner="HUMAN",
            explanation="Script records Confirm* on the existing Chromium session (same as Take Control)",
        )
        await asyncio.sleep(0.3)
        await surface.page.get_by_role("button", name="Confirm create").click()
        await surface.page.wait_for_url("**/workspace**")
        writer.event("human_activity", owner="HUMAN", action="click", target="Confirm create")
        await asyncio.sleep(0.3)
        controller.resume(intervention.id)
        await asyncio.wait_for(pause_task, timeout=10)

        result = RunResult(status="success", code="OK", run_id=writer.run_id, outputs={})
        controller.transition("FINISHED")
        writer.finish(result)

        # Close context so Playwright finalizes the webm.
        video_path = None
        if surface.page:
            video_path = await surface.page.video.path() if surface.page.video else None
        await surface.close()
        if video_path and Path(video_path).is_file():
            dest_video = writer.path / "confirm-handoff.webm"
            shutil.copy2(video_path, dest_video)
            writer.manifest["video"] = "confirm-handoff.webm"
            writer.write("manifest.json", writer.manifest)

        # Export into /evidence/
        dest = evidence_root / writer.run_id
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(writer.path, dest)
        primary_path = evidence_root / "primary.json"
        primary = json.loads(primary_path.read_text()) if primary_path.is_file() else {}
        primary["confirm_handoff"] = writer.run_id
        primary_path.write_text(json.dumps(primary, indent=2) + "\n")
        write_evidence_index(evidence_root)
        print(json.dumps({"run_id": writer.run_id, "code": "OK", "video": bool(dest.exists())}))
    finally:
        process.terminate()
        process.wait(timeout=5)


if __name__ == "__main__":
    asyncio.run(main())
