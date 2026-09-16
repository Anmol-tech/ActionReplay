"""Trusted error vocabulary, not a task script. These rules do not tell discovery what to click."""

from .models import Click, Condition, Locator, Outcome, Target, literal

FRAME_PATH = [
    Locator(strategy="attribute", name="name", value="shell"),
    Locator(strategy="attribute", name="name", value="workspace"),
]
STATUSES = {
    "MEMBER_NOT_FOUND": ("Member not found", "business_outcome"),
    "ACCOUNT_NOT_FOUND": ("Account not found", "business_outcome"),
    "INVALID_MEMBER_ID": ("Invalid member ID", "business_outcome"),
    "INVALID_NICKNAME": ("Invalid nickname", "business_outcome"),
    "PERMISSION_DENIED": ("Permission denied", "failure"),
    "SESSION_EXPIRED": ("Session expired", "intervention"),
    "TRANSIENT_FAILURE": ("Temporary service failure", "recover"),
    "KNOWN_INTERSTITIAL": ("Maintenance notice", "recover"),
    "UNEXPECTED_DIALOG": ("Unexpected verification required", "intervention"),
    "STAFF_VERIFICATION_REQUIRED": ("Staff verification required", "intervention"),
}


def runtime_profile():
    targets = {}
    outcomes = []
    for code, (text, response) in STATUSES.items():
        name = "status_" + code.lower()
        targets[name] = Target(
            frame_path=FRAME_PATH,
            locator=Locator(strategy="text", text=literal(text)),
            description="Trusted runtime status",
        )
        recovery = []
        if response == "recover":
            recovery = [Click(id="dismiss_" + code.lower(), action="click", target="known_continue")]
        outcomes.append(
            Outcome(
                code=code,
                condition=Condition(kind="visible", target=name),
                response=response,
                recovery=recovery,
            )
        )
    targets["known_continue"] = Target(
        frame_path=FRAME_PATH,
        locator=Locator(strategy="role", role="link", text=literal("Continue")),
        description="Trusted interstitial dismissal",
    )
    return targets, outcomes
