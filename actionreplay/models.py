"""Executable JSON vocabulary. Extra fields and dangling references fail closed."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Binding(Model):
    kind: Literal["input", "literal", "variable"]
    name: str | None = None
    value: str | int | bool | None = None

    @model_validator(mode="after")
    def shape(self):
        if self.kind == "literal":
            if self.value is None or self.name is not None:
                raise ValueError("Literal needs value only")
        elif not self.name or self.value is not None:
            raise ValueError("Reference needs name only")
        return self

    def resolve(self, inputs: dict, variables: dict):
        if self.kind == "literal":
            return self.value
        return (inputs if self.kind == "input" else variables)[self.name]


def literal(value: str | int | bool) -> Binding:
    return Binding(kind="literal", value=value)


class Contract(Model):
    type: Literal["string", "integer", "decimal", "boolean", "enum"] = "string"
    required: bool = True
    sensitive: bool = True
    enum: list[str] = Field(default_factory=list)
    pattern: str | None = None
    minimum: int | None = None
    maximum: int | None = None
    variable: str | None = None

    def check(self, value: Any):
        if self.type in {"string", "enum", "decimal"} and not isinstance(value, str):
            raise ValueError("Expected string representation")
        if self.type == "integer" and type(value) is not int:
            raise ValueError("Expected integer")
        if self.type == "boolean" and type(value) is not bool:
            raise ValueError("Expected boolean")
        if self.type == "enum" and value not in self.enum:
            raise ValueError("Unknown enum member")
        if self.pattern and not re.fullmatch(self.pattern, str(value)):
            raise ValueError("Input constraint failed")
        if self.type == "decimal":
            try:
                number = Decimal(value)
                if not number.is_finite():
                    raise ValueError("Non-finite decimal")
                value = format(number, "f")
            except InvalidOperation as exc:
                raise ValueError("Invalid decimal") from exc
        if self.type == "integer":
            if self.minimum is not None and value < self.minimum:
                raise ValueError("Below minimum")
            if self.maximum is not None and value > self.maximum:
                raise ValueError("Above maximum")
        return value


class Locator(Model):
    strategy: Literal["role", "label", "text", "attribute", "anchored"]
    text: Binding | None = None
    role: str | None = None
    name: Literal["name", "title", "placeholder", "id"] | None = None
    value: str | None = None
    # Anchored locator: the unique row containing anchor text, then a semantic child.
    child_role: str | None = None
    child_name: Binding | None = None
    child_tag: Literal["input", "select", "td", "a", "button", "output"] | None = None

    @model_validator(mode="after")
    def shape(self):
        if self.strategy == "attribute":
            if not self.name or self.value is None:
                raise ValueError("Attribute requires name and value")
        elif self.text is None:
            raise ValueError("Text binding required")
        if self.strategy == "role" and not self.role:
            raise ValueError("Role required")
        if self.strategy == "anchored" and not (self.child_role or self.child_tag):
            raise ValueError("Anchored target requires semantic child")
        return self


class Target(Model):
    frame_path: list[Locator] = Field(default_factory=list)
    locator: Locator
    scope: Locator | None = None
    description: str = "UI target"


class Condition(Model):
    kind: Literal["visible", "text_equals", "value_equals", "route", "variable_equals", "all", "any", "not"]
    target: str | None = None
    value: Binding | None = None
    variable: str | None = None
    conditions: list[Condition] = Field(default_factory=list)

    @model_validator(mode="after")
    def shape(self):
        if self.kind in {"all", "any", "not"}:
            if not self.conditions or (self.kind == "not" and len(self.conditions) != 1):
                raise ValueError("Invalid composite condition")
        elif self.kind == "route":
            if not self.value:
                raise ValueError("Route value required")
        elif self.kind == "variable_equals":
            if not self.variable or not self.value:
                raise ValueError("Variable and value required")
        elif not self.target or (self.kind != "visible" and not self.value):
            raise ValueError("Target/value required")
        return self


class StepBase(Model):
    id: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_-]*$")
    preconditions: list[Condition] = Field(default_factory=list)
    postconditions: list[Condition] = Field(default_factory=list)


class Navigate(StepBase):
    action: Literal["navigate"]
    route: Binding


class Click(StepBase):
    action: Literal["click"]
    target: str


class Fill(StepBase):
    action: Literal["fill", "select"]
    target: str
    value: Binding


class Press(StepBase):
    action: Literal["press"]
    target: str
    key: Literal["Tab", "ArrowDown", "ArrowUp", "Escape", "Space"]


class Scroll(StepBase):
    action: Literal["scroll"]
    target: str | None = None
    delta_y: int = Field(default=500, ge=-2000, le=2000)


class Check(StepBase):
    action: Literal["wait_for", "assert"]
    condition: Condition


class Extract(StepBase):
    action: Literal["extract"]
    target: str
    variable: str
    source: Literal["text", "value"] = "text"
    conversion: Literal["text", "integer", "decimal", "currency"] = "text"


Step = Annotated[Navigate | Click | Fill | Press | Scroll | Check | Extract, Field(discriminator="action")]


class Outcome(Model):
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    condition: Condition
    response: Literal["business_outcome", "failure", "intervention", "recover"]
    recovery: list[Step] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def bounded(self):
        if self.response != "recover" and self.recovery:
            raise ValueError("Only recovery outcomes may contain actions")
        if any(s.action not in {"click", "wait_for"} for s in self.recovery):
            raise ValueError("Recovery limited to known dismissal and waits")
        return self


class Application(Model):
    family: str
    surface: Literal["browser"] = "browser"
    versions: list[str] = Field(min_length=1)
    entry_route: str = "/"


class Capability(Model):
    schema_version: Literal["1.0"] = "1.0"
    capability_id: str = Field(pattern=r"^[a-z][a-z0-9-]*$")
    revision: int = Field(default=1, ge=1)
    name: str
    description: str
    source_run_id: str
    application: Application
    inputs: dict[str, Contract]
    outputs: dict[str, Contract]
    targets: dict[str, Target]
    steps: list[Step] = Field(min_length=1, max_length=500)
    outcomes: list[Outcome] = Field(default_factory=list)
    success: list[Condition] = Field(min_length=1)

    @model_validator(mode="after")
    def references(self):
        ids = [s.id for s in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate step IDs")
        variables = {s.variable for s in self.steps if isinstance(s, Extract)}

        def walk(node):
            if isinstance(node, Binding):
                if node.kind == "input" and node.name not in self.inputs:
                    raise ValueError("Undefined input")
                if node.kind == "variable" and node.name not in variables:
                    raise ValueError("Undefined variable")
            if isinstance(node, Model):
                if hasattr(node, "target") and node.target and node.target not in self.targets:
                    raise ValueError("Undefined target")
                if isinstance(node, Condition) and node.variable and node.variable not in variables:
                    raise ValueError("Undefined condition variable")
                for name in type(node).model_fields:
                    walk(getattr(node, name))
            elif isinstance(node, dict):
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)

        walk(self.targets)
        walk(self.steps)
        walk(self.success)
        walk(self.outcomes)
        for contract in self.outputs.values():
            if contract.variable not in variables:
                raise ValueError("Output requires an extracted variable")

        # A declared variable is not necessarily available before its extraction step.
        def variable_references(node):
            if isinstance(node, Binding):
                return {node.name} if node.kind == "variable" else set()
            if isinstance(node, Model):
                found = set()
                if isinstance(node, Condition) and node.variable:
                    found.add(node.variable)
                for field in type(node).model_fields:
                    found.update(variable_references(getattr(node, field)))
                if getattr(node, "target", None):
                    found.update(variable_references(self.targets[node.target]))
                return found
            if isinstance(node, list):
                return set().union(*(variable_references(item) for item in node))
            return set()

        available = set()
        for step in self.steps:
            before = step.model_copy(update={"postconditions": []})
            if variable_references(before) - available:
                raise ValueError("Variable referenced before extraction")
            if isinstance(step, Extract):
                if step.variable in available:
                    raise ValueError("Variable extracted more than once")
                available.add(step.variable)
            if variable_references(step.postconditions) - available:
                raise ValueError("Postcondition variable not available")
        return self

    def validate_inputs(self, inputs: dict):
        if set(inputs) - self.inputs.keys():
            raise ValueError("Unexpected inputs")
        result = {}
        for name, contract in self.inputs.items():
            if name not in inputs:
                if contract.required:
                    raise ValueError("Missing required input")
                continue
            result[name] = contract.check(inputs[name])
        return result


class RunResult(Model):
    status: Literal["success", "business_outcome", "failure"]
    code: str
    run_id: str
    outputs: dict[str, Any] = Field(default_factory=dict)
    step_id: str | None = None
    expected: str | None = None
    observed: str | None = None
    evidence: list[str] = Field(default_factory=list)


class Intervention(Model):
    id: str
    run_id: str
    step_id: str | None = None
    reason: str
    evidence: list[str] = Field(default_factory=list)
    budget_exhausted: bool = False
    goal: str | None = None
    capability_name: str | None = None
    mode: str | None = None
