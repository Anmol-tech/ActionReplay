import json
import logging
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from actionreplay.config import Config, load_config
from actionreplay.evidence import EvidenceError, EvidenceWriter, cleanup, export_runs, save_revision
from actionreplay.models import Capability, RunResult
from actionreplay.policy import AutomationError, Policy
from actionreplay.surface import convert
from tests.helpers import balance_capability


def test_roundtrip_and_leading_zero():
    c = balance_capability()
    assert Capability.model_validate_json(c.model_dump_json()) == c
    assert c.validate_inputs({"member_id": "00123"})["member_id"] == "00123"
    assert convert("$9,876.54", "currency") == "9876.54"
    for invalid in ["$NaN", "1,23.00", "$1.00 extra"]:
        with pytest.raises(AutomationError):
            convert(invalid, "currency")


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d.update(schema_version="2"),
        lambda d: d["steps"][0].update(action="execute_python"),
        lambda d: d["steps"][0].update(target="missing"),
        lambda d: d["steps"][0]["value"].update(name="missing"),
        lambda d: d["outputs"]["balance"].update(variable="missing"),
        lambda d: d.update(secret="hidden"),
    ],
)
def test_invalid_artifacts(mutation):
    data = balance_capability().model_dump(mode="json")
    mutation(data)
    with pytest.raises(ValidationError):
        Capability.model_validate(data)


def test_config(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("discovery:\n  max_steps: 12\n")
    assert load_config(str(path)).discovery.max_steps == 12
    assert load_config(str(path), max_steps=41).discovery.max_steps == 41
    assert Config().discovery.max_steps == 30
    with pytest.raises(ValidationError):
        load_config(str(path), max_steps=0)


def test_policy():
    p = Policy(Config().policy)
    for url in [
        "https://example.com",
        "http://127.0.0.1:8000/commit",
        "http://127.0.0.1:8000/%2e%2e/commit",
        "http://evil@127.0.0.1:8000/",
    ]:
        with pytest.raises(AutomationError):
            p.url(url)
    with pytest.raises(AutomationError):
        p.control("click", "Confirm creation")


def test_evidence_redaction_hash_export_cleanup(tmp_path):
    root = tmp_path / "runs"
    writer = EvidenceWriter(
        root, "replay", {}, sensitive=["PII_CANARY", "00123"], provenance="offline-fixture"
    )
    writer.event("test", text="PII_CANARY", password="secret", url="http://local/?member=00123")
    writer.attach(balance_capability())
    result = RunResult(status="success", code="OK", run_id=writer.run_id, outputs={"balance": "1250.45"})
    writer.finish(result)
    all_data = "\n".join(p.read_text() for p in writer.path.rglob("*.json*"))
    assert "PII_CANARY" not in all_data and "00123" not in all_data and "1250.45" not in all_data
    assert json.loads((writer.path / "manifest.json").read_text())["capability_hash"]
    destination = tmp_path / "evidence"
    export_runs(root, destination, [writer.run_id], sensitive=["PII_CANARY"])
    active = EvidenceWriter(root, "discovery", {})
    old = datetime.now(timezone.utc) - timedelta(days=8)
    writer.manifest["finished_at"] = old.isoformat()
    writer.write("manifest.json", writer.manifest)
    assert cleanup(root, 7) == [writer.run_id]
    assert active.path.exists() and (destination / writer.run_id).exists()


def test_terminal_event_logging_is_structured_and_sanitized(tmp_path, caplog):
    writer = EvidenceWriter(tmp_path / "runs", "discovery", {}, sensitive=["PII_CANARY"])
    with caplog.at_level(logging.INFO, logger="actionreplay.run"):
        writer.event("decision_rejected", code="BAD_DECISION", supplied="PII_CANARY")
    assert '"event":"decision_rejected"' in caplog.text
    assert '"code":"BAD_DECISION"' in caplog.text
    assert "PII_CANARY" not in caplog.text
    assert "[REDACTED]" in caplog.text


def test_immutable_revision_and_write_failure(tmp_path, monkeypatch):
    c = balance_capability()
    save_revision(tmp_path / "capabilities", c)
    with pytest.raises(FileExistsError):
        save_revision(tmp_path / "capabilities", c)
    writer = EvidenceWriter(tmp_path / "runs", "replay", {})

    def fail(*args, **kwargs):
        raise OSError("sensitive OS error")

    monkeypatch.setattr("actionreplay.evidence.atomic_json", fail)
    with pytest.raises(EvidenceError):
        writer.write("result.json", {})
