import argparse
import json
import logging
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path

import httpx
import uvicorn

from .config import load_config
from .evidence import cleanup, export_runs
from .models import Capability

LOGGER = logging.getLogger("actionreplay.cli")


def parser():
    p = argparse.ArgumentParser(prog="actionreplay")
    p.add_argument("--config")
    p.add_argument("--coordinator", default="http://127.0.0.1:8001")
    p.add_argument("--token-file", default=".actionreplay/token")
    p.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Terminal diagnostic verbosity (default: INFO)",
    )
    sub = p.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("--headless", action="store_true", default=None)
    serve.add_argument(
        "--scenario",
        choices=["normal", "permission", "session", "slow", "transient", "interstitial", "dialog"],
    )
    discover = sub.add_parser("discover")
    discover.add_argument("--goal", required=True)
    discover.add_argument("--target", required=True)
    discover.add_argument("--inputs-file", required=True)
    discover.add_argument("--capability", required=True)
    discover.add_argument("--max-steps", type=int)
    discover.add_argument("--max-duration-seconds", type=int)
    replay = sub.add_parser("replay")
    replay.add_argument("--artifact", required=True)
    replay.add_argument("--inputs-file", required=True)
    export = sub.add_parser("export-evidence")
    export.add_argument("run_ids", nargs="+")
    export.add_argument("--destination", default="evidence")
    export.add_argument("--canaries-file")
    sub.add_parser("cleanup")
    schema = sub.add_parser("schema")
    schema.add_argument("--output", default="schemas/capability.schema.json")
    return p


def main():
    args = parser().parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
        stream=sys.stderr,
    )
    try:
        config = load_config(args.config)
        if args.command == "serve":
            from urllib.parse import urlsplit

            from .server import create_app, write_token

            if args.headless is not None:
                config.headless = args.headless
            if args.scenario:
                config.scenario = args.scenario
            mock_url = urlsplit(config.policy.base_url)
            coord_url = urlsplit(args.coordinator)
            if mock_url.hostname != "127.0.0.1" or coord_url.hostname != "127.0.0.1":
                raise ValueError("Serve binds to loopback only")
            token = secrets.token_urlsafe(32)
            write_token(Path(args.token_file), token)
            LOGGER.info(
                "services_starting mock_url=%s coordinator_url=%s model=%s headless=%s scenario=%s",
                config.policy.base_url,
                args.coordinator,
                os.getenv("OPENROUTER_MODEL") or "[NOT_CONFIGURED]",
                config.headless,
                config.scenario,
            )
            env = dict(os.environ, ACTIONREPLAY_SCENARIO=config.scenario)
            child = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "actionreplay.mock_app:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(mock_url.port or 8000),
                    "--no-access-log",
                ],
                env=env,
            )
            print(f"Operator: {args.coordinator}/#{token}", file=sys.stderr)
            try:
                uvicorn.run(
                    create_app(config, token),
                    host="127.0.0.1",
                    port=coord_url.port or 8001,
                    access_log=False,
                    log_level=args.log_level.lower(),
                )
            finally:
                child.terminate()
                child.wait(timeout=10)
                Path(args.token_file).unlink(missing_ok=True)
            return
        if args.command == "schema":
            path = Path(args.output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(Capability.model_json_schema(), indent=2) + "\n")
            print(path)
            return
        if args.command == "cleanup":
            print(json.dumps({"removed": cleanup(config.evidence.directory, config.evidence.retention_days)}))
            return
        if args.command == "export-evidence":
            canaries = json.loads(Path(args.canaries_file).read_text()) if args.canaries_file else []
            export_runs(config.evidence.directory, Path(args.destination), args.run_ids, sensitive=canaries)
            print(json.dumps({"exported": args.run_ids, "destination": args.destination}))
            return
        payload = {
            "mode": "discovery" if args.command == "discover" else "replay",
            "inputs": json.loads(Path(args.inputs_file).read_text()),
        }
        if args.command == "discover":
            payload.update(
                goal=args.goal,
                target=args.target,
                capability_name=args.capability,
                max_steps=args.max_steps,
                max_duration_seconds=args.max_duration_seconds,
            )
        else:
            payload["artifact"] = Capability.model_validate_json(Path(args.artifact).read_text()).model_dump(
                mode="json"
            )
        token = Path(args.token_file).read_text().strip()
        with httpx.Client(
            base_url=args.coordinator, headers={"X-ActionReplay-Token": token}, timeout=15
        ) as client:
            response = client.post("/runs", json=payload)
            response.raise_for_status()
            run_id = response.json()["run_id"]
            print(f"Run {run_id}", file=sys.stderr)
            last_owner = None
            while True:
                response = client.get(f"/runs/{run_id}")
                response.raise_for_status()
                state = response.json()
                if state.get("owner") != last_owner:
                    last_owner = state.get("owner")
                    print(f"Control: {last_owner}", file=sys.stderr)
                    if state.get("intervention"):
                        print(
                            f"Intervention: {state['intervention']['reason']}. Open the operator page.",
                            file=sys.stderr,
                        )
                if state.get("result"):
                    print(json.dumps(state["result"]))
                    if state["result"]["status"] == "failure":
                        raise SystemExit(1)
                    return
                time.sleep(0.5)
    except KeyboardInterrupt:
        print(
            "CLI disconnected; the coordinator retains the live run. Use the operator page to abort.",
            file=sys.stderr,
        )
        raise SystemExit(130) from None
    except Exception as exc:
        # Do not print raw HTTP or validation exceptions, which can contain submitted data.
        LOGGER.error(
            "command_failed command=%s code=%s error_type=%s",
            args.command,
            getattr(exc, "code", type(exc).__name__),
            type(exc).__name__,
            exc_info=LOGGER.isEnabledFor(logging.DEBUG),
        )
        print(json.dumps({"status": "failure", "code": getattr(exc, "code", type(exc).__name__)}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
