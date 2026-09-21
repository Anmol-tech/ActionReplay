"""Loopback coordinator retains the browser while CLI clients wait or disconnect."""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import Field

from .config import Config
from .evidence import EvidenceError, EvidenceWriter
from .models import Capability, Model, RunResult
from .policy import AutomationError, Policy
from .replay import ReplayEngine
from .session import SessionController
from .surface import BrowserSurface

LOGGER = logging.getLogger("actionreplay.server")


class StartRequest(Model):
    mode: Literal["discovery", "replay"]
    goal: str | None = None
    target: str | None = None
    inputs: dict = Field(default_factory=dict)
    capability_name: str = Field(default="discovered-flow", pattern=r"^[a-z][a-z0-9-]*$")
    artifact: Capability | None = None
    max_steps: int | None = Field(default=None, gt=0)
    max_duration_seconds: int | None = Field(default=None, gt=0)


class ControlRequest(Model):
    intervention_id: str
    action: Literal["take", "resume", "abort", "dismiss_dialog"]
    steps: int = Field(default=0, ge=0)
    seconds: int = Field(default=0, ge=0)


class Coordinator:
    def __init__(self, config):
        self.config = config
        self.task = None
        self.evidence = self.controller = self.surface = self.result = None
        self.summary = {}

    async def start(self, request: StartRequest):
        if self.task and not self.task.done():
            raise HTTPException(409, "A run is already active")
        if request.mode == "replay":
            if request.artifact is None:
                # Agent-facing path: catalog id + typed inputs (no embedded artifact body).
                request.artifact = load_latest_capability(request.capability_name)
            try:
                request.artifact.validate_inputs(request.inputs)
            except ValueError:
                raise HTTPException(422, "Invalid capability inputs") from None
        elif not request.goal or not request.target:
            raise HTTPException(422, "Discovery requires goal and target")
        config = self.config.model_copy(deep=True)
        if request.max_steps is not None:
            config.discovery.max_steps = request.max_steps
        if request.max_duration_seconds is not None:
            config.discovery.max_duration_seconds = request.max_duration_seconds
        if request.target:
            Policy(config.policy).url(request.target)
        sensitive = [*request.inputs.values(), os.getenv("OPENROUTER_API_KEY", "")]
        self.evidence = EvidenceWriter(
            config.evidence.directory, request.mode, config.model_dump(mode="json"), sensitive=sensitive
        )
        self.controller = SessionController(self.evidence, config.handoff.timeout_seconds)
        # Caller goal stays in memory and is only shown to the authenticated local operator.
        self.summary = {
            "capability_id": request.artifact.capability_id if request.artifact else request.capability_name,
            "goal": self.evidence.sanitizer.text(request.goal or request.artifact.description),
            "mode": request.mode,
        }
        self.result = None
        self.evidence.event(
            "run_started",
            mode=request.mode,
            capability_id=self.summary["capability_id"],
            input_names=sorted(request.inputs),
            max_steps=config.discovery.max_steps if request.mode == "discovery" else None,
            max_duration_seconds=(
                config.discovery.max_duration_seconds if request.mode == "discovery" else None
            ),
        )
        self.task = asyncio.create_task(self._run(request, config))
        return self.evidence.run_id

    async def _run(self, request, config):
        client = None
        assist = None
        phase = "browser_startup"
        try:
            if self.surface:
                self.evidence.event("previous_browser_closing")
                await self.surface.close()
            self.surface = BrowserSurface(config, self.evidence, lambda: self.controller.owner)
            self.controller.surface = self.surface
            self.evidence.event("browser_starting", headless=config.headless)
            await self.surface.start()
            self.evidence.event("browser_started")
            phase = request.mode
            if request.mode == "replay":
                if (
                    config.execution.assisted_fallback
                    and config.execution.assisted_fallback_max_per_run > 0
                    and os.getenv("OPENROUTER_API_KEY")
                    and os.getenv("OPENROUTER_MODEL")
                ):
                    from .assist import AssistedFallback
                    from .discovery import OpenRouterClient

                    client = OpenRouterClient()
                    assist = AssistedFallback(config, self.surface, self.evidence, client)
                    self.evidence.event("assisted_fallback_enabled", max_per_run=config.execution.assisted_fallback_max_per_run)
                self.result = await ReplayEngine(
                    config, self.surface, self.evidence, self.controller, assist=assist
                ).run(request.artifact, request.inputs)
            else:
                from .discovery import DiscoveryEngine, OpenRouterClient

                client = OpenRouterClient()
                self.result = await DiscoveryEngine(
                    config, self.surface, self.evidence, self.controller, client
                ).run(request.goal, request.target, request.inputs, request.capability_name)
        except Exception as exc:
            code = getattr(exc, "code", "STARTUP_FAILED")
            LOGGER.error(
                "run_failed run_id=%s phase=%s code=%s error_type=%s",
                self.evidence.run_id,
                phase,
                code,
                type(exc).__name__,
                exc_info=LOGGER.isEnabledFor(logging.DEBUG),
            )
            self.result = RunResult(
                status="failure", code=code, run_id=self.evidence.run_id
            )
            try:
                self.evidence.event(
                    "run_failed",
                    code=code,
                    phase=phase,
                    error_type=type(exc).__name__,
                )
                self.evidence.finish(self.result)
            except EvidenceError:
                self.result.code = "EVIDENCE_WRITE_FAILED"
        finally:
            self.controller.owner = "FINISHED"
            if client:
                await client.close()
            # Mid-run pauses keep Chromium open (they happen inside the engine).
            # After a terminal result, close so headed replay does not leave windows around.
            if self.surface:
                if self.evidence:
                    self.evidence.event("browser_closing")
                await self.surface.close()
                self.surface = None
                if self.controller:
                    self.controller.surface = None

    def state(self):
        if not self.evidence:
            return {"state": "idle"}
        return {
            **self.summary,
            "run_id": self.evidence.run_id,
            "state": "finished" if self.result else "running",
            **self.controller.state(),
            "result": self.result.model_dump(mode="json") if self.result else None,
        }

    async def close(self):
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        if self.surface:
            await self.surface.close()


OPERATOR_HTML_PATH = Path(__file__).with_name("operator.html")
CAPABILITY_ROOT = Path("capabilities")
FIXTURE_CAPABILITIES = {
    "offline-balance": Path("examples/offline-balance.json"),
}


def list_capability_catalog():
    """Agent-facing catalog: callable capability ids with typed contracts from latest revision."""
    catalog = []
    if CAPABILITY_ROOT.is_dir():
        for folder in sorted(CAPABILITY_ROOT.iterdir()):
            if not folder.is_dir() or not folder.name.replace("-", "").isalnum() or not folder.name[0].islower():
                continue
            revisions = sorted(int(path.stem) for path in folder.glob("*.json") if path.stem.isdigit())
            if not revisions:
                continue
            latest = revisions[-1]
            entry = {
                "capability_id": folder.name,
                "revisions": revisions,
                "latest_revision": latest,
                "kind": "recorded",
                "invoke": f"POST /runs with mode=replay, capability_name={folder.name}, inputs={{...}}",
            }
            try:
                artifact = Capability.model_validate_json((folder / f"{latest}.json").read_text())
                entry.update(
                    {
                        "description": artifact.description,
                        "inputs": {
                            name: {"type": contract.type, "required": contract.required}
                            for name, contract in artifact.inputs.items()
                        },
                        "outputs": {
                            name: {"type": contract.type, "variable": contract.variable}
                            for name, contract in artifact.outputs.items()
                        },
                    }
                )
            except Exception:
                pass
            catalog.append(entry)
    for capability_id, path in sorted(FIXTURE_CAPABILITIES.items()):
        if path.is_file():
            entry = {
                "capability_id": capability_id,
                "revisions": [1],
                "latest_revision": 1,
                "kind": "fixture",
                "invoke": f"POST /runs with mode=replay, capability_name={capability_id}, inputs={{...}}",
            }
            try:
                artifact = Capability.model_validate_json(path.read_text())
                entry.update(
                    {
                        "description": artifact.description,
                        "inputs": {
                            name: {"type": contract.type, "required": contract.required}
                            for name, contract in artifact.inputs.items()
                        },
                        "outputs": {
                            name: {"type": contract.type, "variable": contract.variable}
                            for name, contract in artifact.outputs.items()
                        },
                    }
                )
            except Exception:
                pass
            catalog.append(entry)
    return catalog


def load_capability_artifact(capability_id: str, revision: int) -> Capability:
    if not capability_id or not capability_id[0].islower() or not all(
        ch.isalnum() or ch == "-" for ch in capability_id
    ):
        raise HTTPException(404, "Unknown capability")
    if capability_id in FIXTURE_CAPABILITIES and FIXTURE_CAPABILITIES[capability_id].is_file():
        path = FIXTURE_CAPABILITIES[capability_id].resolve()
    else:
        path = (CAPABILITY_ROOT / capability_id / f"{revision}.json").resolve()
        root = CAPABILITY_ROOT.resolve()
        if root not in path.parents or not path.is_file():
            raise HTTPException(404, "Unknown capability revision")
    if not path.is_file():
        raise HTTPException(404, "Unknown capability revision")
    try:
        return Capability.model_validate_json(path.read_text())
    except Exception as exc:
        raise HTTPException(422, "Invalid capability artifact") from exc


def load_latest_capability(capability_id: str) -> Capability:
    """Resolve catalog id → latest revision artifact (agent invoke without embedding JSON)."""
    for entry in list_capability_catalog():
        if entry["capability_id"] == capability_id:
            return load_capability_artifact(capability_id, entry["latest_revision"])
    raise HTTPException(404, "Unknown capability")


def create_app(config: Config):
    coordinator = Coordinator(config)
    operator_html = OPERATOR_HTML_PATH.read_text()

    @asynccontextmanager
    async def lifespan(app):
        yield
        await coordinator.close()

    app = FastAPI(lifespan=lifespan)
    app.state.coordinator = coordinator

    @app.middleware("http")
    async def protect(request: Request, call_next):
        from fastapi.responses import JSONResponse

        host = request.headers.get("host", "").split(":")[0]
        origin = request.headers.get("origin")
        expected = "http://" + request.headers.get("host", "")
        if host not in {"127.0.0.1", "localhost", "testserver"} or (origin and origin != expected):
            return JSONResponse({"detail": "Untrusted origin"}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    @app.get("/", response_class=HTMLResponse)
    async def operator():
        return operator_html

    @app.get("/settings")
    async def settings():
        return {
            "target": config.policy.base_url,
            "max_steps": config.discovery.max_steps,
            "max_duration_seconds": config.discovery.max_duration_seconds,
            "model": os.getenv("OPENROUTER_MODEL") or None,
            "model_configured": bool(os.getenv("OPENROUTER_API_KEY") and os.getenv("OPENROUTER_MODEL")),
        }

    @app.get("/capabilities")
    async def capabilities():
        return {"capabilities": list_capability_catalog()}

    @app.get("/capabilities/{capability_id}/{revision}")
    async def capability(capability_id: str, revision: int):
        artifact = load_capability_artifact(capability_id, revision)
        return {
            "artifact": artifact.model_dump(mode="json"),
            "input_names": sorted(artifact.inputs),
            "description": artifact.description,
        }

    @app.post("/runs")
    async def start(request: StartRequest):
        try:
            return {"run_id": await coordinator.start(request)}
        except AutomationError as exc:
            raise HTTPException(422, exc.code) from None

    @app.get("/state")
    async def state():
        result = coordinator.state()
        # Operator does not need extracted output values; only CLI result endpoint returns them.
        if result.get("result"):
            result["result"]["outputs"] = {k: "[REDACTED]" for k in result["result"]["outputs"]}
        return result

    @app.get("/runs/{run_id}")
    async def run_state(run_id: str):
        if not coordinator.evidence or coordinator.evidence.run_id != run_id:
            raise HTTPException(404, "Run not active in this process")
        return coordinator.state()

    @app.get("/snapshot")
    async def snapshot():
        c = coordinator.controller
        if not c or not c.intervention:
            return {}
        import json

        return json.loads((coordinator.evidence.path / c.intervention.evidence[0]).read_text())

    @app.post("/control")
    async def control(request: ControlRequest):
        c = coordinator.controller
        if not c:
            raise HTTPException(409, "No active run")
        try:
            if request.action == "take":
                c.take_control(request.intervention_id)
            elif request.action == "resume":
                c.resume(request.intervention_id, request.steps, request.seconds)
            elif request.action == "abort":
                c.abort(request.intervention_id)
            else:
                c._check_id(request.intervention_id)
                if c.owner != "HUMAN" or not coordinator.surface.dialog:
                    raise AutomationError("NO_HUMAN_DIALOG")
                await coordinator.surface.dialog.dismiss()
                coordinator.surface.dialog = None
                coordinator.evidence.event("human_dialog_dismissed", owner="HUMAN")
        except AutomationError as exc:
            raise HTTPException(409, exc.code) from None
        return c.state()

    return app
