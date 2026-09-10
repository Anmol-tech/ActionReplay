"""All durable run data crosses this boundary. Raw browser/model payloads never do."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from pydantic import Field

from .models import Capability, Model, RunResult

RUN_LOGGER = logging.getLogger("actionreplay.run")


def now():
    return datetime.now(timezone.utc).isoformat()


class EvidenceError(RuntimeError):
    code = "EVIDENCE_WRITE_FAILED"


class Event(Model):
    sequence: int
    timestamp: str
    run_id: str
    owner: str
    event_type: str
    step_id: str | None = None
    details: dict = Field(default_factory=dict)


class Sanitizer:
    def __init__(self, sensitive=()):
        self.values = {str(v) for v in sensitive if str(v)}

    def add(self, value):
        if value is not None and str(value):
            self.values.add(str(value))

    def text(self, value: str):
        for secret in sorted(self.values, key=len, reverse=True):
            value = value.replace(secret, "[REDACTED]")
        value = re.sub(r"(?:sk-|Bearer\s+)[A-Za-z0-9._-]+", "[REDACTED]", value, flags=re.I)
        value = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[REDACTED]", value)
        value = re.sub(r"\b\d{3}-\d{2}-\d{4}\b", "[REDACTED]", value)
        value = re.sub(r"([?&][\w-]+=)[^\s&#\"]+", r"\1[REDACTED]", value)
        return value

    def clean(self, value):
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, dict):
            return {
                k: (
                    "[REDACTED]"
                    if k.lower() in {"password", "token", "api_key", "cookie", "authorization"}
                    else self.clean(v)
                )
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [self.clean(v) for v in value]
        return value


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False) as f:
            name = f.name
            json.dump(value, f, indent=2, ensure_ascii=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def capability_bytes(capability: Capability) -> bytes:
    return json.dumps(capability.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()


class EvidenceWriter:
    def __init__(self, root: Path, mode: str, config: dict, sensitive=(), provenance="live"):
        self.run_id = uuid4().hex
        self.path = root / self.run_id
        self.sanitizer = Sanitizer(sensitive)
        self.sequence = 0
        self.manifest = {
            "run_id": self.run_id,
            "mode": mode,
            "started_at": now(),
            "state": "running",
            "software_version": "0.1.0",
            "schema_version": "1.0",
            "provenance": provenance,
            "configuration": config,
        }
        self.write("manifest.json", self.manifest)

    def write(self, relative: str, data):
        try:
            atomic_json(self.path / relative, self.sanitizer.clean(data))
        except OSError as exc:
            raise EvidenceError("Cannot persist evidence") from exc

    def event(self, event_type: str, owner="AUTOMATION", step_id=None, **details):
        self.sequence += 1
        clean_details = self.sanitizer.clean(details)
        record = Event(
            sequence=self.sequence,
            timestamp=now(),
            run_id=self.run_id,
            owner=owner,
            event_type=event_type,
            step_id=step_id,
            details=clean_details,
        )
        try:
            with (self.path / "events.jsonl").open("a") as f:
                f.write(record.model_dump_json() + "\n")
                f.flush()
                os.fsync(f.fileno())
        except OSError as exc:
            raise EvidenceError("Cannot append evidence") from exc
        RUN_LOGGER.info(
            "%s",
            json.dumps(
                {
                    "run_id": self.run_id,
                    "sequence": self.sequence,
                    "owner": owner,
                    "event": event_type,
                    "step_id": step_id,
                    "details": clean_details,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )

    def snapshot(self, data):
        relative = f"snapshots/{self.sequence + 1:06d}.json"
        self.write(relative, data)
        self.event("snapshot", evidence=relative)
        return relative

    def attach(self, capability: Capability):
        data = capability.model_dump(mode="json")
        # Exact executable content must not be silently altered by redaction.
        if self.sanitizer.clean(data) != data:
            raise ValueError("Artifact contains invocation values or sensitive text")
        self.write("capability.json", data)
        self.manifest.update(
            capability_id=capability.capability_id,
            revision=capability.revision,
            capability_hash=hashlib.sha256(capability_bytes(capability)).hexdigest(),
            source_run_id=capability.source_run_id,
        )
        self.write("manifest.json", self.manifest)

    def finish(self, result: RunResult):
        public = result.model_dump(mode="json")
        public["outputs"] = {key: "[REDACTED]" for key in result.outputs}
        public["outputs_validated"] = result.status == "success"
        self.write("result.json", public)
        self.event("run_completed", owner="FINISHED", status=result.status, code=result.code)
        self.manifest.update(state="finished", finished_at=now(), status=result.status)
        self.write("manifest.json", self.manifest)


def save_revision(root: Path, capability: Capability):
    folder = root / capability.capability_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{capability.revision}.json"
    # Hard link atomically publishes a complete file and fails if the revision exists.
    fd, temp = tempfile.mkstemp(dir=folder)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(capability.model_dump_json(indent=2).encode() + b"\n")
            f.flush()
            os.fsync(f.fileno())
        os.link(temp, path)
    finally:
        os.unlink(temp)
    return path


def export_runs(root: Path, destination: Path, run_ids: list[str], sensitive=()):
    sanitizer = Sanitizer(sensitive)
    manifests = []
    for run_id in run_ids:
        if not re.fullmatch(r"[a-f0-9]{32}", run_id):
            raise ValueError("Invalid run ID")
        folder = root / run_id
        manifest = json.loads((folder / "manifest.json").read_text())
        if manifest["state"] != "finished":
            raise ValueError("Cannot export unfinished run")
        for path in folder.rglob("*"):
            if path.is_symlink():
                raise ValueError("Symlink in evidence")
            if path.is_file():
                content = path.read_text()
                if sanitizer.text(content) != content:
                    raise ValueError("Export scan detected sensitive content")
        manifests.append(manifest)
    destination.mkdir(parents=True, exist_ok=True)
    for manifest in manifests:
        shutil.copytree(root / manifest["run_id"], destination / manifest["run_id"], dirs_exist_ok=True)
    rows = [
        "# Evidence index",
        "",
        "Provenance is explicit. Offline fixtures are not genuine discovery evidence.",
        "",
    ]
    for path in sorted(destination.glob("*/manifest.json")):
        m = json.loads(path.read_text())
        result = json.loads((path.parent / "result.json").read_text())
        rows.append(
            f"- [{m['run_id']}]({m['run_id']}/manifest.json) — {m['mode']}, "
            f"{m['provenance']}, scenario `{m.get('scenario', 'default')}`, "
            f"result `{result['code']}`. "
            f"[Events]({m['run_id']}/events.jsonl), [capability]({m['run_id']}/capability.json)."
        )
    (destination / "index.md").write_text("\n".join(rows) + "\n")


def cleanup(root: Path, retention_days: int):
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    removed = []
    for path in root.glob("*/manifest.json"):
        if path.is_symlink() or path.parent.is_symlink():
            continue
        m = json.loads(path.read_text())
        if m.get("state") == "finished" and datetime.fromisoformat(m["finished_at"]) < cutoff:
            shutil.rmtree(path.parent)
            removed.append(path.parent.name)
    return removed
