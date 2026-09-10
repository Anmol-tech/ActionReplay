"""Explicit offline fixtures, never imported by the production discovery engine."""

from actionreplay.models import (
    Application,
    Binding,
    Capability,
    Click,
    Condition,
    Contract,
    Extract,
    Fill,
    Locator,
    Target,
    literal,
)
from actionreplay.profile import FRAME_PATH, runtime_profile


def balance_capability():
    targets, outcomes = runtime_profile()

    def target(name, strategy, text, role=None, child_tag=None):
        targets[name] = Target(
            frame_path=FRAME_PATH,
            locator=Locator(strategy=strategy, text=literal(text), role=role, child_tag=child_tag),
            description="Offline fixture target",
        )

    target("search_input", "label", "Member ID")
    target("search_button", "role", "Search", "button")
    target("open_member", "role", "Open member", "link")
    target("savings_link", "role", "Savings", "link")
    target("balance_heading", "role", "Savings balance", "heading")
    target("amount", "anchored", "Amount", child_tag="output")

    def visible(name):
        return Condition(kind="visible", target=name)

    steps = [
        Fill(
            id="enter_member",
            action="fill",
            target="search_input",
            value=Binding(kind="input", name="member_id"),
            preconditions=[visible("search_input")],
        ),
        Click(
            id="search",
            action="click",
            target="search_button",
            preconditions=[visible("search_button")],
            postconditions=[visible("open_member")],
        ),
        Click(
            id="open",
            action="click",
            target="open_member",
            preconditions=[visible("open_member")],
            postconditions=[visible("savings_link")],
        ),
        Click(
            id="savings",
            action="click",
            target="savings_link",
            preconditions=[visible("savings_link")],
            postconditions=[visible("balance_heading")],
        ),
        Extract(
            id="read_balance",
            action="extract",
            target="amount",
            variable="balance",
            conversion="currency",
            preconditions=[visible("balance_heading")],
        ),
    ]
    return Capability(
        capability_id="offline-balance",
        name="Offline balance reference",
        description="Hand-authored test fixture; NOT genuine LLM discovery",
        source_run_id="offline-manual-reference",
        application=Application(family="legacy-bank", versions=["1.0"]),
        inputs={"member_id": Contract()},
        outputs={"balance": Contract(type="decimal", variable="balance")},
        targets=targets,
        steps=steps,
        outcomes=outcomes,
        success=[visible("balance_heading")],
    )
