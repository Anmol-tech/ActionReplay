import socket
import subprocess
import sys
import time

import httpx
import pytest


@pytest.fixture
def mock_server():
    processes = []

    def start(scenario="normal"):
        import os

        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
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
        processes.append(process)
        for _ in range(100):
            try:
                if httpx.get(url, timeout=0.2).status_code == 200:
                    return url
            except httpx.HTTPError:
                pass
            time.sleep(0.05)
        raise RuntimeError("Mock server did not start")

    yield start
    for process in processes:
        process.terminate()
        process.wait(timeout=10)
