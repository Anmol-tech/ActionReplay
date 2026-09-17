from urllib.parse import unquote, urljoin, urlsplit

from .config import PolicyConfig


class AutomationError(RuntimeError):
    def __init__(
        self,
        code: str,
        expected: str = "Allowed, unambiguous UI state",
        details: dict | None = None,
    ):
        self.code = code
        self.expected = expected
        self.details = details or {}
        super().__init__(code)


IRREVERSIBLE_CONFIRM_LABELS = frozenset(
    {
        "Confirm transfer",
        "Confirm create",
        "Confirm delete",
        "Confirm creation",
    }
)

# Review screens that show an irreversible Confirm* button. Resume after
# HUMAN_CONFIRMATION_REQUIRED requires leaving these paths (operator clicked Confirm).
CONFIRMATION_REVIEW_PATHS = frozenset(
    {
        "/review",
        "/create-review",
        "/transfer-review",
        "/delete-confirm",
    }
)


def is_irreversible_confirm_label(identity: str) -> bool:
    return identity in IRREVERSIBLE_CONFIRM_LABELS or identity.startswith("Confirm ")


def observation_irreversible_confirms(observation: dict) -> list[str]:
    """Visible Confirm* labels that commit irreversible bank changes."""
    found = []
    for frame in observation.get("frames") or []:
        for element in frame.get("elements") or []:
            text = element.get("text") or ""
            if is_irreversible_confirm_label(text):
                found.append(text)
    return found


def goal_stops_before_irreversible_confirm(goal: str) -> bool:
    """True when the goal is satisfied on the review/confirmation screen without committing.

    Matches assignment-style goals such as "reach the confirmation screen" and
    explicit review-only wording. Completing create/transfer/delete still requires human Confirm.
    """
    text = (goal or "").lower()
    markers = (
        "reach the confirmation",
        "reach confirmation",
        "confirmation screen",
        "stop at review",
        "stop on the",
        "stop on transfer review",
        "stop on create",
        "stop on delete",
        "do not confirm",
        "don't confirm",
        "without confirm",
        "review only",
        "prepare a ",
        "prepare creating",
        "prepare deleting",
        "prepare opening",
    )
    return any(marker in text for marker in markers)


def confirmation_result_visible(observation: dict) -> bool:
    """True when the post-commit confirmation/result UI is visible."""
    markers = (
        "Confirmation reference",
        "Member created",
        "Transfer posted",
        "Member deleted",
        "Sub-account request accepted",
        "Request accepted",
    )
    for frame in observation.get("frames") or []:
        for element in frame.get("elements") or []:
            text = element.get("text") or ""
            if any(marker in text for marker in markers):
                return True
    return False



class Policy:
    def __init__(self, config: PolicyConfig):
        self.config = config
        base = urlsplit(config.base_url)
        if base.scheme not in {"http", "https"} or base.username or base.password:
            raise ValueError("Invalid base URL")
        self.origin = (base.scheme, base.hostname, base.port or (443 if base.scheme == "https" else 80))

    def url(self, url: str):
        parsed = urlsplit(url)
        origin = (parsed.scheme, parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
        path = unquote(parsed.path or "/")
        if (
            parsed.username
            or parsed.password
            or origin != self.origin
            or path not in self.config.allowed_routes
            or ".." in path.split("/")
        ):
            raise AutomationError("POLICY_ROUTE_BLOCKED")
        return url

    def route(self, route: str):
        if not route.startswith("/") or route.startswith("//"):
            raise AutomationError("POLICY_ROUTE_BLOCKED")
        return self.url(urljoin(self.config.base_url, route))

    def action(self, action: str):
        if action not in self.config.allowed_actions:
            raise AutomationError("POLICY_ACTION_BLOCKED")

    def control(self, action: str, identity: str, key: str | None = None):
        allowed_clicks = self.config.safe_click_labels
        if action == "press" and key in {"Tab", "ArrowDown", "ArrowUp", "Escape"}:
            allowed_clicks = [*allowed_clicks, *self.config.safe_field_names]
        if action in {"click", "press"} and identity not in allowed_clicks:
            if is_irreversible_confirm_label(identity):
                raise AutomationError("HUMAN_CONFIRMATION_REQUIRED")
            raise AutomationError("POLICY_RISKY_CONTROL")
        if action in {"fill", "select"} and identity not in self.config.safe_field_names:
            raise AutomationError("POLICY_UNKNOWN_FIELD")
