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
            raise AutomationError("POLICY_RISKY_CONTROL")
        if action in {"fill", "select"} and identity not in self.config.safe_field_names:
            raise AutomationError("POLICY_UNKNOWN_FIELD")
