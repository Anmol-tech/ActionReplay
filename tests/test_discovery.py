"""Offline protocol tests. These exercise the live UI but do not claim a genuine LLM run."""

import asyncio
import json

import pytest

from actionreplay.config import Config
from actionreplay.discovery import (
    FINISH_EXAMPLE,
    Decision,
    DiscoveryEngine,
    Recorder,
    coerce_decision_arguments,
    completion_hint,
    rejection_guidance,
)
from actionreplay.models import Binding, Click, Condition, Contract, Extract, Fill
from actionreplay.policy import AutomationError
from actionreplay.replay import ReplayEngine
from tests.test_browser import runtime, wait_intervention


class FixtureModel:
    model = "offline-scripted-test-double"

    def __init__(self, review=False):
        self.index = 0
        self.review = review

    async def validate(self):
        pass

    async def decide(self, goal, inputs, observation, history, policy):
        assert observation["screenshot"]
        nodes = [e for f in observation["frames"] for e in f["elements"] if e["ref"]]

        def ref(label=None, text=None, tag=None):
            return next(
                n["ref"]
                for n in nodes
                if (label is None or n["label"] == label)
                and (text is None or n["text"] == text)
                and (tag is None or n["tag"] == tag)
            )

        i = self.index
        self.index += 1
        metadata = {"model": self.model, "usage": {"total_tokens": 0}}
        if i == 0:
            step = Fill(
                id="fill",
                action="fill",
                target=ref(label="Member ID", tag="input"),
                value=Binding(kind="input", name="member_id"),
            )
        elif i == 1:
            step = Click(id="search", action="click", target=ref(text="Search", tag="button"))
        elif i == 2:
            step = Click(id="open", action="click", target=ref(text="Open member", tag="a"))
        elif not self.review:
            if i == 3:
                step = Click(id="savings", action="click", target=ref(text="Savings", tag="a"))
            elif i == 4:
                step = Extract(
                    id="read",
                    action="extract",
                    target=ref(tag="output"),
                    variable="balance",
                    conversion="currency",
                )
            else:
                return Decision(
                    kind="finish",
                    outputs={"balance": Contract(type="decimal", variable="balance")},
                    success=[Condition(kind="visible", target=ref(text="Savings balance", tag="h2"))],
                ), metadata
        else:
            if i == 3:
                step = Click(id="prepare", action="click", target=ref(text="Prepare sub-account", tag="a"))
            elif i == 4:
                step = Fill(
                    id="select",
                    action="select",
                    target=ref(tag="select"),
                    value=Binding(kind="input", name="account_type"),
                )
            elif i == 5:
                step = Fill(
                    id="nickname",
                    action="fill",
                    target=ref(label="Nickname", tag="input"),
                    value=Binding(kind="input", name="nickname"),
                )
            elif i == 6:
                step = Click(id="review", action="click", target=ref(text="Review", tag="button"))
            elif i == 7:
                step = Extract(
                    id="read",
                    action="extract",
                    target=ref(text=inputs["nickname"], tag="output"),
                    variable="nickname",
                )
            else:
                return Decision(
                    kind="finish",
                    outputs={"nickname": Contract(variable="nickname")},
                    success=[Condition(kind="visible", target=ref(text="Sub-account review", tag="h2"))],
                ), metadata
        return Decision(kind="action", step=step), metadata


def test_unparameterized_value_is_rejected_without_terminal_output(capsys):
    recorder = Recorder({"member_id": "00123"}, Config())
    with pytest.raises(AutomationError, match="UNPARAMETERIZED_VALUE"):
        recorder.bind({"kind": "literal", "name": None, "value": "/member/00123"})
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert "literal URLs" in rejection_guidance("UNPARAMETERIZED_VALUE")


def test_finish_completion_hint_after_extract():
    hint = completion_hint(
        [
            {
                "action": "extract",
                "result": "completed",
                "extracted_variables": ["balance"],
                "last_extract": {"variable": "balance", "conversion": "currency"},
            }
        ]
    )
    assert '"kind":"finish"' in hint
    assert '"variable":"balance"' in hint
    assert '"type":"decimal"' in hint
    guidance = rejection_guidance("MODEL_DECISION_SCHEMA_INVALID")
    assert FINISH_EXAMPLE in guidance

    coerced = json.loads(
        coerce_decision_arguments(
            {
                "kind": "done",
                "action": "finish",
                "step": {"id": "x", "action": "click", "target": "e1"},
                "outputs": {"balance": "balance"},
                "success": {"kind": "visible", "target": 1},
            },
            {"member_id": "00123"},
        )
    )
    assert coerced["kind"] == "finish"
    assert coerced["step"] is None
    assert "action" not in coerced
    assert coerced["outputs"]["balance"]["variable"] == "balance"
    assert coerced["success"][0]["target"] == "e1"
    Decision.model_validate(coerced)

    fill = json.loads(
        coerce_decision_arguments(
            {
                "kind": "action",
                "step": {
                    "id": "fill",
                    "action": "fill",
                    "target": "e2",
                    "value": {"kind": "input", "name": "member_id", "value": "00123"},
                },
            },
            {"member_id": "00123"},
        )
    )
    assert fill["step"]["value"] == {"kind": "input", "name": "member_id"}


@pytest.mark.parametrize("review", [False, True])
async def test_record_then_replay_live_ui(tmp_path, mock_server, review):
    config, evidence, controller, surface = await runtime(tmp_path, mock_server())
    # Explicit provenance despite exercising the real browser and recorder.
    evidence.manifest["mode"] = "discovery"
    evidence.manifest["provenance"] = "offline-scripted-model"
    inputs = {"member_id": "00123"}
    if review:
        inputs.update(account_type="Savings", nickname="Holiday fund")
    evidence.sanitizer.values.update(str(v) for v in inputs.values())
    try:
        engine = DiscoveryEngine(config, surface, evidence, controller, FixtureModel(review))
        result = await engine.run(
            "Reach review" if review else "Read balance",
            config.policy.base_url,
            inputs,
            "test-review" if review else "test-balance",
            tmp_path / "capabilities",
        )
        assert result.status == "success", result
        from actionreplay.models import Capability

        artifact = Capability.model_validate_json((evidence.path / "capability.json").read_text())
        assert artifact.steps
        assert "00123" not in artifact.model_dump_json()
        assert "Holiday fund" not in artifact.model_dump_json()
    finally:
        await surface.close()
    config, evidence, controller, surface = await runtime(tmp_path, config.policy.base_url)
    try:
        new_inputs = {"member_id": "00678"}
        if review:
            new_inputs.update(account_type="Checking", nickname="Travel fund")
        result = await ReplayEngine(config, surface, evidence, controller).run(artifact, new_inputs)
        assert result.status == "success", result
        assert result.outputs == ({"nickname": "Travel fund"} if review else {"balance": "9876.54"})
    finally:
        await surface.close()


class InvalidModel:
    model = "offline-invalid-test-double"
    calls = 0

    async def validate(self):
        pass

    async def decide(self, *args):
        self.calls += 1
        raise ValueError("Invalid model tool response")


async def test_step_budget_counts_invalid_decisions(tmp_path, mock_server):
    config, evidence, controller, surface = await runtime(tmp_path, mock_server())
    config.discovery.max_steps = 2
    config.discovery.max_consecutive_no_progress = 10
    client = InvalidModel()
    try:
        task = asyncio.create_task(
            DiscoveryEngine(config, surface, evidence, controller, client).run(
                "Any goal",
                config.policy.base_url,
                {"member_id": "00123"},
                "budget-test",
                tmp_path / "capabilities",
            )
        )
        intervention = await wait_intervention(controller)
        assert intervention.reason == "DISCOVERY_BUDGET_EXHAUSTED"
        assert client.calls == 2
        controller.take_control(intervention.id)
        with pytest.raises(AutomationError, match="BUDGET_EXTENSION_REQUIRED"):
            controller.resume(intervention.id)
        controller.resume(intervention.id, steps=1, seconds=30)
        for _ in range(200):
            if controller.intervention and controller.intervention.id != intervention.id:
                break
            await asyncio.sleep(0.025)
        assert client.calls == 3
        controller.abort(controller.intervention.id)
        result = await task
        assert result.code == "OPERATOR_ABORTED"
    finally:
        await surface.close()
