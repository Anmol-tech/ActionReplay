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
    # Bounded OpenRouter single-step recovery on replay UI drift (stretch goal). Off by default
    # so replay stays model-free unless explicitly enabled with OpenRouter credentials.
    assisted_fallback: bool = False
    assisted_fallback_max_per_run: int = Field(default=1, ge=0, le=3)


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
        "/verify",
        "/transfer",
        "/transfer-review",
        "/create-member",
        "/create-review",
        "/delete-member",
        "/delete-confirm",
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
    # Irreversible confirms (Confirm transfer/create/delete/creation) are intentionally omitted.
    safe_click_labels: list[str] = [
        "Search",
        "Open member",
        "Savings",
        "Checking",
        "Prepare sub-account",
        "Review",
        "Back",
        "Continue",
        "Transfer funds",
        "Create member",
        "Delete member",
        "Review transfer",
        "Continue to review",
        "Review create",
        "Review delete",
    ]
    safe_field_names: list[str] = [
        "Member ID",
        "Account type",
        "Nickname",
        "member_id",
        "account_type",
        "nickname",
        "Amount",
        "amount",
        "From account",
        "from_account",
        "To account",
        "to_account",
        "New member ID",
        "new_member_id",
        "Display name",
        "display_name",
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
        "Transfer funds",
        "Transfer review",
        "Create member",
        "Create member review",
        "Delete member",
        "Delete member review",
        "Staff verification required",
        "From account",
        "From account:",
        "To account",
        "To account:",
        "Amount:",
        "New member ID",
        "New member ID:",
        "Display name",
        "Display name:",
        "Review transfer",
        "Continue to review",
        "Review create",
        "Review delete",
        "Verify staff authorization",
        "Confirmation reference",
        "Insufficient funds",
        "Invalid account combination",
        "Member already exists",
    ]
    approved_attributes: dict[str, list[str]] = {
        "name": [
            "shell",
            "workspace",
            "member_id",
            "account_type",
            "nickname",
            "amount",
            "from_account",
            "to_account",
            "new_member_id",
            "display_name",
        ],
        "title": ["Bank shell", "Workspace"],
        "id": ["member", "nickname", "amount", "new_member_id", "display_name"],
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
    scenario: Literal[
        "normal", "permission", "session", "slow", "transient", "interstitial", "dialog", "drift"
    ] = ("normal")


def load_config(path: str | None = None, **overrides) -> Config:
    data = yaml.safe_load(Path(path).read_text()) if path else {}
    data = data or {}
    for key in ("max_steps", "max_duration_seconds"):
        if overrides.get(key) is not None:
            data.setdefault("discovery", {})[key] = overrides[key]
    return Config.model_validate(data)
