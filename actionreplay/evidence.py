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


def write_evidence_index(destination: Path):
    """Curated index: look-here-first primary runs, then stretch, then archive."""
    primary_path = destination / "primary.json"
    primary = {}
    if primary_path.is_file():
        primary = json.loads(primary_path.read_text())

    def row(run_id: str, note: str | None = None) -> str | None:
        manifest_path = destination / run_id / "manifest.json"
        if not manifest_path.is_file():
            return None
        m = json.loads(manifest_path.read_text())
        result = json.loads((destination / run_id / "result.json").read_text())
        stretch = m.get("stretch")
        stretch_bit = f", stretch `{stretch}`" if stretch else ""
        note_bit = f" — {note}" if note else ""
        extras = []
        events = destination / run_id / "events.jsonl"
        cap = destination / run_id / "capability.json"
        video = destination / run_id / "confirm-handoff.webm"
        if events.is_file():
            extras.append(f"[Events]({run_id}/events.jsonl)")
        if cap.is_file():
            extras.append(f"[capability]({run_id}/capability.json)")
        if video.is_file():
            extras.append(f"[video]({run_id}/confirm-handoff.webm)")
        return (
            f"- [{run_id}]({run_id}/manifest.json) — {m['mode']}, {m['provenance']}, "
            f"scenario `{m.get('scenario', 'default')}`{stretch_bit}, result `{result['code']}`"
            f"{note_bit}. " + ", ".join(extras) + "."
        )

    look = []
    labels = [
        ("live_discovery", "current-mock live discovery"),
        ("live_replay_ok", "alternate-input replay"),
        ("live_replay_not_found", "MEMBER_NOT_FOUND business outcome"),
    ]
    for key, label in labels:
        rid = primary.get(key)
        if rid:
            line = row(rid, label)
            if line:
                look.append(line)

    stretch = []
    assist = primary.get("assisted_fallback")
    if assist:
        line = row(assist, "one policy-checked assist click on label drift")
        if line:
            stretch.append(line)
    handoff = primary.get("confirm_handoff")
    if handoff:
        line = row(handoff, "Confirm* Take Control → click Confirm → Resume (same session)")
        if line:
            stretch.append(line)
    stability = primary.get("stability_report")
    if stability and (destination / stability).is_file():
        stretch.append(
            f"- [{stability}]({stability}) — stretch multi-run stability: N deterministic "
            "replays of savings-balance with pass rate."
        )

    primary_ids = {primary.get(k) for k in ("live_discovery", "live_replay_ok", "live_replay_not_found", "assisted_fallback", "confirm_handoff")}
    archive = []
    for path in sorted(destination.glob("*/manifest.json")):
        rid = path.parent.name
        if rid in primary_ids:
            continue
        line = row(rid)
        if line:
            archive.append(line)

    lines = [
        "# Evidence index",
        "",
        "Provenance is explicit. Offline fixtures are not genuine discovery evidence.",
        "",
        "## Look here first (current LegacyBank mock)",
        "",
        *look,
        "",
        "## Stretch demos",
        "",
        *(stretch or ["- _(none yet)_"]),
        "",
        "## Archive / offline fixtures",
        "",
        *archive,
        "",
    ]
    (destination / "index.md").write_text("\n".join(lines))


def export_runs(root: Path, destination: Path, run_ids: list[str], sensitive=()):
    sanitizer = Sanitizer(sensitive)
    manifests = []
    text_suffixes = {".json", ".jsonl", ".md", ".txt", ".yaml", ".yml"}
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
            if path.is_file() and path.suffix.lower() in text_suffixes:
                content = path.read_text()
                if sanitizer.text(content) != content:
                    raise ValueError("Export scan detected sensitive content")
        manifests.append(manifest)
    destination.mkdir(parents=True, exist_ok=True)
    for manifest in manifests:
        shutil.copytree(root / manifest["run_id"], destination / manifest["run_id"], dirs_exist_ok=True)
    write_evidence_index(destination)


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
