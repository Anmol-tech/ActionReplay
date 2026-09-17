"""Bounded LLM assist for replay UI drift. Never open-ended; policy-checked single actions only."""

from __future__ import annotations

from .discovery import OpenRouterClient
from .policy import AutomationError

ASSIST_SYSTEM = """You are assisting a FAILED deterministic replay of a bank UI workflow.
Take exactly ONE policy-safe action to unblock the current step. Do not finish.
Do not click irreversible confirms (Confirm transfer, Confirm create, Confirm delete, Confirm creation).
Use only the perform tool with kind=action. Targets must be current observation e-refs.
Prefer clicking a visibly equivalent control when a label drifted.
"""


class AssistedFallback:
    def __init__(self, config, surface, evidence, client: OpenRouterClient | None = None):
        self.config = config
        self.surface = surface
        self.evidence = evidence
        self.client = client
        self.used = 0

    @property
    def available(self):
        return (
            self.config.execution.assisted_fallback
            and self.config.execution.assisted_fallback_max_per_run > 0
            and self.client is not None
            and self.used < self.config.execution.assisted_fallback_max_per_run
        )

    async def try_recover(self, step, capability, inputs, variables):
        if not self.available:
            return False
        self.used += 1
        observation = await self.surface.observe()
        self.evidence.event(
            "assisted_fallback_started",
            step_id=step.id,
            attempt=self.used,
        )
        history = [
            {
                "result": "replay_blocked",
                "step_action": step.action,
                "guidance": "Take one safe action to satisfy the blocked step's intent.",
            }
        ]
        policy = {
            "allowed_actions": self.config.policy.allowed_actions,
            "safe_click_labels": self.config.policy.safe_click_labels,
            "safe_fields": self.config.policy.safe_field_names,
            "forbidden_clicks": [
                "Confirm transfer",
                "Confirm create",
                "Confirm delete",
                "Confirm creation",
            ],
        }
        try:
            decision, metadata = await self.client.decide(
                (
                    f"Replay step {step.id} ({step.action}) is blocked. "
                    "Choose one safe UI action to progress past this blockage."
                ),
                {name: "[INPUT]" for name in inputs},
                observation,
                history,
                policy,
                system_prompt=ASSIST_SYSTEM,
            )
            self.evidence.event("assisted_fallback_model_response", step_id=step.id, **metadata)
            if decision.kind != "action" or decision.step is None:
                raise AutomationError("ASSIST_REQUIRES_ACTION")
            assist_step = decision.step
            assist_step.id = f"assist_{step.id}_{self.used}"
            await self.surface.execute_action(assist_step, capability.targets, inputs, variables)
            self.evidence.event(
                "assisted_fallback_action",
                step_id=step.id,
                assist_step_id=assist_step.id,
                action=assist_step.action,
            )
            return True
        except Exception as exc:
            self.evidence.event(
                "assisted_fallback_failed",
                step_id=step.id,
                code=getattr(exc, "code", type(exc).__name__),
            )
            return False

    async def close(self):
        if self.client:
            await self.client.close()
            self.client = None
