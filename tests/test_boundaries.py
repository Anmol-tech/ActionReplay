import asyncio

import pytest
from playwright.async_api import Error as PlaywrightError
from pydantic import ValidationError

from actionreplay.evidence import EvidenceError
from actionreplay.models import Capability, Click, Locator, Target, literal
from actionreplay.policy import AutomationError
from actionreplay.replay import ReplayEngine
from tests.helpers import balance_capability
from tests.test_browser import runtime, wait_intervention


def test_variable_before_extraction_rejected():
    data = balance_capability().model_dump(mode="json")
    data["steps"][0]["value"] = {"kind": "variable", "name": "balance"}
    with pytest.raises(ValidationError, match="before extraction"):
        Capability.model_validate(data)


async def test_policy_blocks_real_side_effect(tmp_path, mock_server):
    config, evidence, controller, surface = await runtime(tmp_path, mock_server())
    try:
        await surface.page.goto(config.policy.base_url)
        frame = surface.page.frame(name="workspace")
        await frame.evaluate(
            "() => {window.clicked=0;let b=document.createElement('button');b.textContent='Confirm creation';b.onclick=()=>window.clicked++;document.body.append(b)}"
        )
        target = Target(
            frame_path=balance_capability().targets["search_button"].frame_path,
            locator=Locator(strategy="role", role="button", text=literal("Confirm creation")),
        )
        with pytest.raises(AutomationError, match="POLICY_RISKY_CONTROL"):
            await surface.execute_action(
                Click(id="commit", action="click", target="commit"), {"commit": target}, {}, {}
            )
        assert await frame.evaluate("window.clicked") == 0
        with pytest.raises(PlaywrightError):
            await frame.evaluate("fetch('/commit', {method:'POST'})")
        assert surface.blocked == "POLICY_ROUTE_BLOCKED"
        # Human ownership may submit the irreversible form; request must not be aborted.
        surface.blocked = None
        controller.owner = "HUMAN"
        status = await frame.evaluate(
            "async () => (await fetch('/commit', {method:'POST', redirect:'follow'})).status"
        )
        assert status == 200
        assert surface.blocked is None
    finally:
        await surface.close()


async def test_evidence_failure_prevents_actions(tmp_path, mock_server, monkeypatch):
    config, evidence, controller, surface = await runtime(tmp_path, mock_server())
    try:

        def fail(*args, **kwargs):
            raise EvidenceError("test")

        monkeypatch.setattr(evidence, "write", fail)
        result = await ReplayEngine(config, surface, evidence, controller).run(
            balance_capability(), {"member_id": "00123"}
        )
        assert result.code == "EVIDENCE_WRITE_FAILED"
        assert surface.page.url == "about:blank"
    finally:
        await surface.close()


async def test_zero_recovery_and_incompatible_ui(tmp_path, mock_server):
    config, evidence, controller, surface = await runtime(tmp_path, mock_server("transient"))
    config.execution.max_recovery_attempts = 0
    try:
        result = await ReplayEngine(config, surface, evidence, controller).run(
            balance_capability(), {"member_id": "00123"}
        )
        assert result.code == "RECOVERY_EXHAUSTED"
    finally:
        await surface.close()
    config, evidence, controller, surface = await runtime(tmp_path, mock_server())
    config.startup_text = "Different application version"
    try:
        result = await ReplayEngine(config, surface, evidence, controller).run(
            balance_capability(), {"member_id": "00123"}
        )
        assert result.code == "INCOMPATIBLE_APPLICATION_UI"
        assert "action_requested" not in (evidence.path / "events.jsonl").read_text()
    finally:
        await surface.close()


async def test_invalid_resume_stays_paused(tmp_path, mock_server):
    config, evidence, controller, surface = await runtime(tmp_path, mock_server("session"))
    try:
        task = asyncio.create_task(
            ReplayEngine(config, surface, evidence, controller).run(
                balance_capability(), {"member_id": "00123"}
            )
        )
        intervention = await wait_intervention(controller)
        controller.take_control(intervention.id)
        controller.resume(intervention.id)  # session was not restored
        for _ in range(100):
            if "resume_rejected" in (evidence.path / "events.jsonl").read_text():
                break
            await asyncio.sleep(0.025)
        assert controller.owner == "PAUSED" and not task.done()
        assert "resume_rejected" in (evidence.path / "events.jsonl").read_text()
        with pytest.raises(AutomationError, match="STALE_INTERVENTION"):
            controller.take_control("old-intervention")
        controller.abort(intervention.id)
        assert (await task).code == "OPERATOR_ABORTED"
    finally:
        await surface.close()


async def test_frame_request_policy_applies_to_popups(tmp_path, mock_server):
    config, evidence, controller, surface = await runtime(tmp_path, mock_server())
    try:
        await surface.page.goto(config.policy.base_url)
        await surface.page.evaluate("window.open('/commit')")
        await asyncio.sleep(0.15)
        assert surface.blocked in {"POLICY_ROUTE_BLOCKED", "UNEXPECTED_POPUP"}
        with pytest.raises(AutomationError):
            surface.assert_owner()
    finally:
        await surface.close()
