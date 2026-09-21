"""Stretch: multi-run stability signal for a saved capability.

Replays the same artifact N times against the live mock and writes
evidence/stability.md (pass rate + per-run codes).

  uv run python scripts/stability_report.py
  uv run python scripts/stability_report.py --n 8 --inputs examples/member-b.json
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

from actionreplay.config import Config
from actionreplay.evidence import EvidenceWriter, write_evidence_index
from actionreplay.models import Capability
from actionreplay.replay import ReplayEngine
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


async def one_replay(artifact: Capability, inputs: dict, url: str, runs_dir: Path, index: int):
    config = Config(headless=True)
    config.policy.base_url = url
    config.evidence.directory = runs_dir
    writer = EvidenceWriter(
        config.evidence.directory,
        "replay",
        config.model_dump(mode="json"),
        sensitive=list(inputs.values()),
        provenance="offline-artifact-real-browser",
    )
    writer.manifest["scenario"] = "stability"
    writer.manifest["stability_index"] = index
    writer.write("manifest.json", writer.manifest)
    controller = SessionController(writer, 30)
    surface = BrowserSurface(config, writer, lambda: controller.owner)
    controller.surface = surface
    try:
        await surface.start()
        result = await ReplayEngine(config, surface, writer, controller).run(artifact, inputs)
        return {
            "index": index,
            "run_id": writer.run_id,
            "status": result.status,
            "code": result.code,
            "ok": result.status == "success" and result.code == "OK",
        }
    finally:
        await surface.close()


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--artifact",
        default="capabilities/savings-balance/2.json",
        help="Capability JSON to replay",
    )
    parser.add_argument("--inputs", default="examples/member-b.json")
    parser.add_argument("--n", type=int, default=5, help="Number of replay attempts")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    artifact_path = root / args.artifact
    if not artifact_path.is_file():
        # Fall back to fixture if discovered revision missing.
        artifact_path = root / "examples/offline-balance.json"
    artifact = Capability.model_validate_json(artifact_path.read_text())
    inputs = json.loads((root / args.inputs).read_text())
    runs_dir = root / "runs" / "stability"

    process, url = await serve_mock()
    rows = []
    try:
        for i in range(1, args.n + 1):
            row = await one_replay(artifact, inputs, url, runs_dir, i)
            rows.append(row)
            print(json.dumps(row))
    finally:
        process.terminate()
        process.wait(timeout=5)

    passed = sum(1 for r in rows if r["ok"])
    rate = (passed / len(rows)) * 100 if rows else 0.0
    report = root / "evidence" / "stability.md"
    lines = [
        "# Multi-run stability",
        "",
        f"Artifact: `{artifact_path.relative_to(root)}` (`{artifact.capability_id}` rev {artifact.revision})",
        f"Inputs: `{args.inputs}`",
        f"Attempts: **{len(rows)}** · Passes: **{passed}** · Pass rate: **{rate:.0f}%**",
        "",
        "| # | run_id | status | code |",
        "|---|---|---|---|",
    ]
    for r in rows:
        lines.append(f"| {r['index']} | `{r['run_id']}` | {r['status']} | `{r['code']}` |")
    lines.extend(
        [
            "",
            "This stretch reports a flakiness signal for deterministic replay. "
            "It does not gate draft→approved promotion (that remains a deliberate cut).",
            "",
        ]
    )
    report.write_text("\n".join(lines))

    primary_path = root / "evidence" / "primary.json"
    primary = json.loads(primary_path.read_text()) if primary_path.is_file() else {}
    primary["stability_report"] = "stability.md"
    primary_path.write_text(json.dumps(primary, indent=2) + "\n")
    write_evidence_index(root / "evidence")
    print(json.dumps({"passed": passed, "n": len(rows), "pass_rate_pct": rate, "report": str(report)}))


if __name__ == "__main__":
    asyncio.run(main())
