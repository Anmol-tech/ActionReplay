import asyncio
import json

import pytest

from actionreplay.config import Config
from actionreplay.evidence import EvidenceWriter
from actionreplay.models import Click
from actionreplay.policy import AutomationError
from actionreplay.replay import ReplayEngine
from actionreplay.session import SessionController
from actionreplay.surface import BrowserSurface
from tests.helpers import balance_capability, transfer_review_capability


async def runtime(tmp_path, url):
    config = Config(headless=True)
    config.policy.base_url = url
    config.execution.action_timeout_seconds = 2
    config.handoff.timeout_seconds = 4
    evidence = EvidenceWriter(
        tmp_path / "runs",
        "replay",
        config.model_dump(mode="json"),
        sensitive=["00123", "00678"],
        provenance="offline-fixture",
    )
    controller = SessionController(evidence, config.handoff.timeout_seconds)
    surface = BrowserSurface(config, evidence, lambda: controller.owner)
    controller.surface = surface
    await surface.start()
    return config, evidence, controller, surface


@pytest.mark.parametrize(
    "scenario,member,status,code,balance",
    [
        ("normal", "00123", "success", "OK", "1250.45"),
        ("normal", "00678", "success", "OK", "9876.54"),
        ("normal", "00000", "business_outcome", "MEMBER_NOT_FOUND", None),
        ("normal", "invalid", "business_outcome", "INVALID_MEMBER_ID", None),
        ("permission", "00123", "failure", "PERMISSION_DENIED", None),
        ("slow", "00123", "success", "OK", "1250.45"),
        ("transient", "00123", "success", "OK", "1250.45"),
        ("interstitial", "00123", "success", "OK", "1250.45"),
    ],
)
async def test_replay(tmp_path, mock_server, scenario, member, status, code, balance, monkeypatch):
    # If any accidental model call is introduced, this raises before a network request.
    def forbidden(*args, **kwargs):
        raise AssertionError("Replay invoked a model")

    monkeypatch.setattr("actionreplay.discovery.OpenRouterClient.__init__", forbidden)
    config, evidence, controller, surface = await runtime(tmp_path, mock_server(scenario))
    try:
        result = await ReplayEngine(config, surface, evidence, controller).run(
            balance_capability(), {"member_id": member}
        )
        assert (result.status, result.code) == (status, code), result
        if balance:
            assert result.outputs["balance"] == balance
    finally:
        await surface.close()


async def wait_intervention(controller):
    for _ in range(200):
        if controller.intervention:
            return controller.intervention
        await asyncio.sleep(0.025)
    raise AssertionError("No intervention")


@pytest.mark.parametrize(
    "scenario,manual_label", [("session", "Restore session"), ("dialog", "Resolve verification")]
)
async def test_handoff_same_session(tmp_path, mock_server, scenario, manual_label):
    config, evidence, controller, surface = await runtime(tmp_path, mock_server(scenario))
    try:
        browser_context, page = surface.context, surface.page
        task = asyncio.create_task(
            ReplayEngine(config, surface, evidence, controller).run(
                balance_capability(), {"member_id": "00123"}
            )
        )
        intervention = await wait_intervention(controller)
        cookie_before = await surface.context.cookies()
        controller.take_control(intervention.id)
        with pytest.raises(AutomationError, match="CONTROL_NOT_OWNED"):
            await surface.execute_action(
                Click(id="forbidden", action="click", target="search_button"),
                balance_capability().targets,
                {},
                {},
            )
        # Explicit simulated human for tests. This uses the same page while owner is HUMAN.
        frame = surface.page.frame(name="workspace")
        await frame.get_by_role("link", name=manual_label).click()
        controller.resume(intervention.id)
        result = await task
        assert result.status == "success", result
        assert surface.context is browser_context and surface.page is page
        assert (await surface.context.cookies())[0]["value"] == cookie_before[0]["value"]
        events = (evidence.path / "events.jsonl").read_text()
        assert '"event_type":"human_activity"' in events
        assert "00123" not in events
    finally:
        await surface.close()


async def test_assisted_fallback_on_drift(tmp_path, mock_server):
    class ScriptedAssist:
        def __init__(self, surface):
            self.surface = surface
            self.calls = 0

        async def try_recover(self, step, capability, inputs, variables):
            self.calls += 1
            frame = self.surface.page.frame(name="workspace")
            await frame.get_by_role("button", name="Continue to review").click()
            await frame.get_by_role("heading", name="Transfer review").wait_for()
            return True

    config, evidence, controller, surface = await runtime(tmp_path, mock_server("drift"))
    assist = ScriptedAssist(surface)
    try:
        result = await ReplayEngine(config, surface, evidence, controller, assist=assist).run(
            transfer_review_capability(), {"member_id": "00123"}
        )
        assert (result.status, result.code) == ("success", "OK"), result
        assert assist.calls == 1
        assert result.outputs["amount"] == "25.00"
        events = (evidence.path / "events.jsonl").read_text()
        assert "step_completed_by_assist" in events
    finally:
        await surface.close()


async def test_observation_and_ambiguous_target(tmp_path, mock_server):
    config, evidence, controller, surface = await runtime(tmp_path, mock_server())
    try:
        await surface.page.goto(config.policy.base_url)
        observation = await surface.observe()
        assert observation["screenshot"]
        assert any(e["label"] == "Member ID" for f in observation["frames"] for e in f["elements"])
        await surface.page.frame(name="workspace").evaluate(
            "() => {let p=document.createElement('p');p.hidden=true;p.textContent='HIDDEN_CANARY';document.body.append(p)}"
        )
        assert "HIDDEN_CANARY" not in json.dumps((await surface.observe())["frames"])
        await surface.page.frame(name="workspace").evaluate(
            "() => document.body.insertAdjacentHTML('beforeend','<button>Search</button>')"
        )
        with pytest.raises(AutomationError, match="AMBIGUOUS_TARGET"):
            await surface.resolve_target(balance_capability().targets["search_button"], {}, {})
    finally:
        await surface.close()


async def test_api_auth_and_transitions(tmp_path, monkeypatch):
    import httpx

    from actionreplay.server import create_app

    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-test-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "qwen/test-model")
    app = create_app(Config())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        page = await client.get("/")
        assert page.status_code == 200
        assert "New discovery" in page.text
        assert "Replay capability" in page.text
        assert "synthetic-test-key" not in page.text
        assert (await client.get("/state")).status_code == 200
        settings = await client.get("/settings")
        assert settings.json() == {
            "target": "http://127.0.0.1:8000",
            "max_steps": 30,
            "max_duration_seconds": 300,
            "model": "qwen/test-model",
            "model_configured": True,
        }
        assert "synthetic-test-key" not in settings.text
        catalog = await client.get("/capabilities")
        assert catalog.status_code == 200
        assert any(item["capability_id"] == "offline-balance" for item in catalog.json()["capabilities"])
        artifact = await client.get("/capabilities/offline-balance/1")
        assert artifact.status_code == 200
        assert artifact.json()["artifact"]["capability_id"] == "offline-balance"
        assert (
            await client.get(
                "/state", headers={"Origin": "https://evil.example"}
            )
        ).status_code == 403
