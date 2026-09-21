"""Process-level smoke test: actual CLI -> HTTP coordinator -> real browser -> JSON output."""

import asyncio
import json
import os
import signal
import socket
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from playwright.async_api import async_playwright


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def test_cli_operator_smoke(tmp_path):
    root = Path(__file__).resolve().parents[1]
    mock_port, coordinator_port = free_port(), free_port()
    config = tmp_path / "config.yaml"
    config.write_text(
        f"policy:\n  base_url: http://127.0.0.1:{mock_port}\nevidence:\n  directory: {tmp_path / 'runs'}\n"
    )
    url = f"http://127.0.0.1:{coordinator_port}"
    command = [
        sys.executable,
        "-m",
        "actionreplay.cli",
        "--config",
        str(config),
        "--coordinator",
        url,
    ]
    server_log = tmp_path / "server.log"
    server_log_stream = server_log.open("w")
    process = subprocess.Popen(
        [*command, "serve", "--headless"],
        stdout=subprocess.DEVNULL,
        stderr=server_log_stream,
        env={
            **os.environ,
            "OPENROUTER_API_KEY": "synthetic-ui-test-key",
            "OPENROUTER_MODEL": "qwen/test-model",
        },
    )
    try:
        async with httpx.AsyncClient() as client:
            for _ in range(200):
                try:
                    if (await client.get(url + "/")).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.025)
            else:
                pytest.fail("Coordinator did not start")
            child = await asyncio.create_subprocess_exec(
                *command,
                "replay",
                "--artifact",
                str(root / "examples/offline-balance.json"),
                "--inputs-file",
                str(root / "examples/member-b.json"),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(child.communicate(), 25)
            assert child.returncode == 0, stderr.decode()
            result = json.loads(stdout)
            assert result["outputs"] == {"balance": "9876.54"}
            state = (await client.get(url + "/state")).json()
            assert state["result"]["outputs"] == {"balance": "[REDACTED]"}
            async with async_playwright() as pw:
                browser = await pw.chromium.launch()
                page = await browser.new_page(viewport={"width": 1200, "height": 1100})
                await page.goto(url)
                await page.get_by_role("heading", name="FINISHED", exact=True).wait_for()
                assert await page.get_by_role("heading", name="New discovery").is_visible()
                assert await page.get_by_role("tab", name="Discover").is_visible()
                assert await page.get_by_role("tab", name="Replay").is_visible()
                assert await page.get_by_label("Goal", exact=True).input_value() == (
                    "Find the savings balance for the supplied member"
                )
                assert await page.get_by_label("Start from").input_value() == "savings"
                assert await page.get_by_label("Target URL").input_value() == (
                    f"http://127.0.0.1:{mock_port}"
                )
                assert await page.get_by_label("Maximum steps").input_value() == "30"
                assert await page.get_by_role("button", name="Start discovery").is_enabled()
                assert "qwen/test-model" in await page.locator("#model").inner_text()
                assert "synthetic-ui-test-key" not in await page.content()
                assert await page.locator("#handoff").is_hidden()

                submitted = {}

                async def capture_discovery(route, request):
                    submitted.update(request.post_data_json)
                    await route.fulfill(
                        status=200,
                        content_type="application/json",
                        body='{"run_id":"synthetic-browser-run"}',
                    )

                await page.route("**/runs", capture_discovery)
                await page.get_by_role("button", name="Start discovery").click()
                await asyncio.sleep(0.1)
                assert submitted == {
                    "mode": "discovery",
                    "goal": "Find the savings balance for the supplied member",
                    "target": f"http://127.0.0.1:{mock_port}",
                    "inputs": {"member_id": "00123"},
                    "capability_name": "savings-balance",
                    "max_steps": 30,
                    "max_duration_seconds": 300,
                }

                submitted.clear()
                await page.get_by_role("tab", name="Replay").click()
                assert await page.get_by_role("heading", name="Replay capability").is_visible()
                assert await page.get_by_role("button", name="Start replay").is_enabled()
                assert "offline-balance" in await page.locator("#replay-capability").inner_text()
                await page.locator("#replay-capability").select_option("offline-balance")
                await asyncio.sleep(0.15)
                await page.get_by_role("button", name="Start replay").click()
                await asyncio.sleep(0.1)
                assert submitted["mode"] == "replay"
                assert submitted["inputs"] == {"member_id": "00678"}
                assert submitted["artifact"]["capability_id"] == "offline-balance"
                # QA-only screenshot of a synthetic run; never part of persisted run evidence.
                await page.screenshot(path=str(tmp_path / "operator.png"), full_page=True)
                await browser.close()
            log_text = server_log.read_text()
            for event in ["run_started", "browser_started", "action_completed", "run_completed"]:
                assert f'"event":"{event}"' in log_text
            assert "synthetic-ui-test-key" not in log_text
            assert "00678" not in log_text
            assert "9876.54" not in log_text
    finally:
        process.send_signal(signal.SIGINT)
        process.wait(timeout=15)
        server_log_stream.close()
