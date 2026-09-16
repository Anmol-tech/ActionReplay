"""Deterministic executor. Intentionally imports no model client or discovery module."""

from __future__ import annotations

import asyncio
import time

from playwright.async_api import TimeoutError as BrowserTimeout

from .evidence import EvidenceError
from .models import Capability, RunResult
from .policy import AutomationError


class TerminalOutcome(Exception):
    def __init__(self, status, code):
        self.status = status
        self.code = code


class ReplayEngine:
    def __init__(self, config, surface, evidence, controller, assist=None):
        self.config = config
        self.surface = surface
        self.evidence = evidence
        self.controller = controller
        self.assist = assist
        self.variables = {}
        self.recoveries = {}
        self.step_id = None

    async def conditions(self, conditions, capability, inputs):
        return all(
            [
                await self.surface.evaluate_condition(c, capability.targets, inputs, self.variables)
                for c in conditions
            ]
        )

    async def outcomes(self, capability, inputs, step=None):
        # Rule order is artifact order, capped by configured recovery counters.
        for rule in capability.outcomes:
            if not await self.surface.evaluate_condition(
                rule.condition, capability.targets, inputs, self.variables
            ):
                continue
            self.evidence.event(
                "runtime_outcome", step_id=self.step_id, code=rule.code, response=rule.response
            )
            if rule.response in {"business_outcome", "failure"}:
                raise TerminalOutcome(rule.response, rule.code)
            if rule.response == "recover":
                count = self.recoveries.get(rule.code, 0)
                if count >= self.config.execution.max_recovery_attempts:
                    raise AutomationError("RECOVERY_EXHAUSTED")
                self.recoveries[rule.code] = count + 1
                self.evidence.event("retry", step_id=self.step_id, code=rule.code, attempt=count + 1)
                for recovery in rule.recovery:
                    # Runtime policy restricts these to trusted controls, irrespective of artifact claims.
                    await self.surface.execute_action(recovery, capability.targets, inputs, self.variables)
                return True

            async def restored(rule=rule):
                if await self.surface.evaluate_condition(
                    rule.condition, capability.targets, inputs, self.variables
                ):
                    return False
                return await self.resume_valid(step, capability, inputs)

            await self.controller.pause(rule.code, self.step_id, validator=restored)
            return True
        return False

    async def wait_conditions(self, conditions, capability, inputs, step):
        deadline = time.monotonic() + self.config.execution.action_timeout_seconds
        while True:
            while await self.outcomes(capability, inputs, step):
                pass
            if await self.conditions(conditions, capability, inputs):
                return True
            if time.monotonic() >= deadline:
                return False
            await asyncio.sleep(0.05)

    async def resume_valid(self, step, capability, inputs):
        if self.surface.dialog:
            return False
        if len(self.surface.context.pages) != 1:
            return False
        for frame in self.surface.page.frames:
            if frame.url.startswith("http"):
                try:
                    self.surface.policy.url(frame.url)
                except AutomationError:
                    return False
        if step is None:
            # Discovery has no recorded next step yet. It will re-observe and reason;
            # replay always supplies real success conditions or an interrupted step.
            if not capability.success:
                return True
            return await self.conditions(capability.success, capability, inputs)
        if step.postconditions and await self.conditions(step.postconditions, capability, inputs):
            return True
        if not step.preconditions:
            return False
        return await self.conditions(step.preconditions, capability, inputs)

    async def execute_step(self, step, capability, inputs):
        self.step_id = step.id
        attempts = 0
        while True:
            try:
                while await self.outcomes(capability, inputs, step):
                    pass
                if not await self.wait_conditions(step.preconditions, capability, inputs, step):
                    raise AutomationError("PRECONDITION_FAILED")
                started = time.monotonic()
                self.evidence.event(
                    "action_requested",
                    step_id=step.id,
                    action=step.action,
                    target=getattr(step, "target", None),
                )
                self.evidence.event("policy_decision", step_id=step.id, decision="checking")
                await self.surface.execute_action(step, capability.targets, inputs, self.variables)
                self.evidence.event(
                    "action_completed",
                    step_id=step.id,
                    action=step.action,
                    duration_ms=round((time.monotonic() - started) * 1000),
                )
                while await self.outcomes(capability, inputs, step):
                    pass
                if not await self.wait_conditions(step.postconditions, capability, inputs, step):
                    raise AutomationError("POSTCONDITION_FAILED")
                self.evidence.event("checkpoint", step_id=step.id, verified=True)
                return
            except (BrowserTimeout, AutomationError) as exc:
                code = getattr(exc, "code", "ACTION_TIMEOUT")
                safe_retry = step.action in {"extract", "assert", "wait_for", "fill", "select"}
                if (
                    code in {"ACTION_TIMEOUT", "TARGET_NOT_FOUND"}
                    and safe_retry
                    and attempts < self.config.execution.max_recovery_attempts
                ):
                    attempts += 1
                    self.evidence.event("retry", step_id=step.id, code=code, attempt=attempts)
                    await asyncio.sleep(min(0.2 * attempts, 1))
                    continue
                if code in {"HANDOFF_TIMEOUT", "OPERATOR_ABORTED", "RECOVERY_EXHAUSTED"}:
                    raise
                # Bounded optional LLM assist (stretch): one policy-checked action, then retry.
                if (
                    self.assist
                    and code
                    in {
                        "TARGET_NOT_FOUND",
                        "PRECONDITION_FAILED",
                        "POSTCONDITION_FAILED",
                        "ACTION_TIMEOUT",
                    }
                    and await self.assist.try_recover(step, capability, inputs, self.variables)
                ):
                    if step.postconditions and await self.conditions(
                        step.postconditions, capability, inputs
                    ):
                        self.evidence.event("step_completed_by_assist", step_id=step.id)
                        return
                    continue
                snapshot = self.evidence.snapshot(await self.surface.capture_sanitized_evidence())
                self.evidence.event("action_blocked", step_id=step.id, code=code, evidence=snapshot)

                async def validator():
                    return await self.resume_valid(step, capability, inputs)

                await self.controller.pause(code, step.id, validator=validator)
                if step.postconditions and await self.conditions(step.postconditions, capability, inputs):
                    self.evidence.event("step_completed_by_human", step_id=step.id)
                    return

    async def run(self, capability: Capability, inputs):
        try:
            inputs = capability.validate_inputs(inputs)
            if (
                capability.application.family != self.config.application_family
                or self.config.application_version not in capability.application.versions
            ):
                raise AutomationError("INCOMPATIBLE_APPLICATION")
            self.surface.policy.route(capability.application.entry_route)
            self.evidence.attach(capability)
            await self.surface.page.goto(
                self.surface.policy.route(capability.application.entry_route), wait_until="domcontentloaded"
            )
            await self.surface.verify_application()
            for step in capability.steps:
                await self.execute_step(step, capability, inputs)
            while await self.outcomes(capability, inputs):
                pass
            if not await self.conditions(capability.success, capability, inputs):
                raise AutomationError("SUCCESS_CHECKPOINT_FAILED")
            outputs = {
                name: contract.check(self.variables[contract.variable])
                for name, contract in capability.outputs.items()
            }
            result = RunResult(status="success", code="OK", run_id=self.evidence.run_id, outputs=outputs)
        except TerminalOutcome as exc:
            snapshot = self.evidence.snapshot(await self.surface.capture_sanitized_evidence())
            result = RunResult(
                status=exc.status,
                code=exc.code,
                run_id=self.evidence.run_id,
                step_id=self.step_id,
                evidence=[snapshot],
            )
        except EvidenceError:
            return RunResult(
                status="failure",
                code="EVIDENCE_WRITE_FAILED",
                run_id=self.evidence.run_id,
                step_id=self.step_id,
            )
        except Exception as exc:
            code = getattr(
                exc,
                "code",
                "INVALID_ARTIFACT_OR_INPUT"
                if isinstance(exc, (ValueError, KeyError))
                else "EXECUTION_FAILED",
            )
            snapshot = self.evidence.snapshot(await self.surface.capture_sanitized_evidence())
            result = RunResult(
                status="failure",
                code=code,
                run_id=self.evidence.run_id,
                step_id=self.step_id,
                expected=getattr(exc, "expected", "Validated capability and UI checkpoint"),
                observed="See sanitized snapshot",
                evidence=[snapshot],
            )
        self.controller.transition("FINISHED")
        self.evidence.finish(result)
        return result
