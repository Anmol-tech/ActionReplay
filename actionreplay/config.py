from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field

from .models import Model


class DiscoveryConfig(Model):
    max_steps: int = Field(default=30, gt=0)
    max_duration_seconds: int = Field(default=300, gt=0)
    max_consecutive_no_progress: int = Field(default=3, gt=0)


class ExecutionConfig(Model):
    action_timeout_seconds: float = Field(default=10, gt=0)
    max_recovery_attempts: int = Field(default=2, ge=0)


class HandoffConfig(Model):
    timeout_seconds: float = Field(default=900, gt=0)


class EvidenceConfig(Model):
    directory: Path = Path("runs")
    retention_days: int = Field(default=7, gt=0)


class PolicyConfig(Model):
    base_url: str = "http://127.0.0.1:8000"
    allowed_routes: list[str] = [
        "/",
        "/shell",
        "/workspace",
        "/search",
        "/member",
        "/account",
        "/new",
        "/review",
        "/restore",
        "/continue",
    ]
    allowed_actions: list[str] = [
        "navigate",
        "click",
        "fill",
        "select",
        "press",
        "scroll",
        "wait_for",
        "assert",
        "extract",
    ]
    # Only these visible control identities may cause clicks. Unknown controls fail closed.
    safe_click_labels: list[str] = [
        "Search",
        "Open member",
        "Savings",
        "Checking",
        "Prepare sub-account",
        "Review",
        "Back",
        "Continue",
    ]
    safe_field_names: list[str] = [
        "Member ID",
        "Account type",
        "Nickname",
        "member_id",
        "account_type",
        "nickname",
    ]
    approved_literals: list[str] = [
        "Savings",
        "Checking",
        "Member ID",
        "Account type",
        "Nickname",
        "Search",
        "Open member",
        "Prepare sub-account",
        "Review",
        "Back",
        "Continue",
        "Savings balance",
        "Checking balance",
        "Amount",
        "Member details",
        "Sub-account review",
        "Account type:",
        "Nickname:",
        "Member servicing",
        "Search results",
    ]
    approved_attributes: dict[str, list[str]] = {
        "name": ["shell", "workspace", "member_id", "account_type", "nickname"],
        "title": ["Bank shell", "Workspace"],
        "id": ["member", "nickname"],
        "placeholder": [],
    }


class Config(Model):
    discovery: DiscoveryConfig = Field(default_factory=DiscoveryConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    handoff: HandoffConfig = Field(default_factory=HandoffConfig)
    evidence: EvidenceConfig = Field(default_factory=EvidenceConfig)
    policy: PolicyConfig = Field(default_factory=PolicyConfig)
    application_family: str = "legacy-bank"
    application_version: str = "1.0"
    startup_text: str = "LegacyBank 1.0 — Staff workspace"
    headless: bool = False
    scenario: Literal["normal", "permission", "session", "slow", "transient", "interstitial", "dialog"] = (
        "normal"
    )


def load_config(path: str | None = None, **overrides) -> Config:
    data = yaml.safe_load(Path(path).read_text()) if path else {}
    data = data or {}
    for key in ("max_steps", "max_duration_seconds"):
        if overrides.get(key) is not None:
            data.setdefault("discovery", {})[key] = overrides[key]
    return Config.model_validate(data)
