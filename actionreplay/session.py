from __future__ import annotations

import asyncio
from uuid import uuid4

from .models import Intervention
from .policy import AutomationError


class SessionController:
    """One event loop, one owner, one pending transfer. No concurrent action workers."""

    def __init__(self, evidence, timeout: float):
        self.evidence = evidence
        self.timeout = timeout
        self.owner = "AUTOMATION"
        self.intervention: Intervention | None = None
        self.surface = None
        self.signal = asyncio.Event()
        self.resume_requested = False
        self.aborted = False
        self.extensions = {"steps": 0, "seconds": 0}
        self.paused_seconds = 0.0
        self.context: dict = {}

    def state(self):
        return {
            "owner": self.owner,
            "intervention": self.intervention.model_dump(mode="json") if self.intervention else None,
        }

    def transition(self, owner):
        self.evidence.event("ownership_transfer", owner=owner, previous=self.owner, next=owner)
        self.owner = owner

    async def pause(self, reason, step_id=None, validator=None, budget=False):
        pause_started = asyncio.get_running_loop().time()
        initial_extensions = dict(self.extensions)
        self.transition("PAUSED")
        snapshot = self.evidence.snapshot(await self.surface.capture_sanitized_evidence())
        self.intervention = Intervention(
            id=uuid4().hex,
            run_id=self.evidence.run_id,
            step_id=step_id,
            reason=reason,
            evidence=[snapshot],
            budget_exhausted=budget,
            goal=self.context.get("goal"),
            capability_name=self.context.get("capability_name"),
            mode=self.context.get("mode"),
        )
        self.evidence.event(
            "intervention",
            owner="PAUSED",
            step_id=step_id,
            intervention_id=self.intervention.id,
            reason=reason,
            evidence=snapshot,
            goal=self.intervention.goal,
            capability_name=self.intervention.capability_name,
            mode=self.intervention.mode,
        )
        deadline = asyncio.get_running_loop().time() + self.timeout
        try:
            while True:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise AutomationError("HANDOFF_TIMEOUT")
                await asyncio.wait_for(self.signal.wait(), remaining)
                self.signal.clear()
                if self.aborted:
                    raise AutomationError("OPERATOR_ABORTED")
                if self.resume_requested:
                    self.resume_requested = False
                    valid = not budget or (
                        self.extensions["steps"] > initial_extensions["steps"]
                        and self.extensions["seconds"] > initial_extensions["seconds"]
                    )
                    if valid:
                        valid = await self.surface.resume_ready()
                    if valid and validator:
                        valid = await validator()
                    if not valid:
                        self.evidence.event(
                            "resume_rejected", owner="PAUSED", code="INCOMPATIBLE_RESUME_STATE"
                        )
                        continue
                    self.transition("AUTOMATION")
                    return
        except asyncio.TimeoutError as exc:
            raise AutomationError("HANDOFF_TIMEOUT") from exc
        finally:
            self.paused_seconds += asyncio.get_running_loop().time() - pause_started
            self.intervention = None

    def take_control(self, intervention_id):
        self._check_id(intervention_id)
        if self.owner != "PAUSED":
            raise AutomationError("INVALID_CONTROL_TRANSITION")
        # Drop abort residue from blocked human navigations (e.g. Confirm → /commit).
        if self.surface is not None:
            self.surface.blocked = None
        self.transition("HUMAN")

    def resume(self, intervention_id, steps=0, seconds=0):
        self._check_id(intervention_id)
        if self.owner != "HUMAN":
            raise AutomationError("INVALID_CONTROL_TRANSITION")
        if not isinstance(steps, int) or not isinstance(seconds, int) or steps < 0 or seconds < 0:
            raise AutomationError("INVALID_BUDGET_EXTENSION")
        if self.intervention.budget_exhausted and (steps <= 0 or seconds <= 0):
            raise AutomationError("BUDGET_EXTENSION_REQUIRED")
        self.extensions["steps"] += steps
        self.extensions["seconds"] += seconds
        self.transition("PAUSED")
        self.resume_requested = True
        self.signal.set()

    def abort(self, intervention_id):
        self._check_id(intervention_id)
        self.aborted = True
        self.signal.set()

    def _check_id(self, intervention_id):
        if not self.intervention or self.intervention.id != intervention_id:
            raise AutomationError("STALE_INTERVENTION")
