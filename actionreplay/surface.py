"""Visible browser observations and deterministic action execution."""

from __future__ import annotations

import asyncio
import base64
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

from playwright.async_api import async_playwright

from .config import Config
from .models import Condition, Locator, Target, literal
from .policy import AutomationError, Policy


class SurfaceAdapter(Protocol):
    async def observe(self) -> dict: ...
    async def resolve_target(self, target: Target, inputs: dict, variables: dict): ...
    async def execute_action(self, step, targets: dict, inputs: dict, variables: dict): ...
    async def evaluate_condition(
        self, condition: Condition, targets: dict, inputs: dict, variables: dict
    ) -> bool: ...
    async def extract_value(self, step, targets: dict, inputs: dict, variables: dict): ...
    async def capture_sanitized_evidence(self) -> dict: ...


# Read only rendered elements, their user-visible labels, and approved identifying attributes.
# No application JS globals, hidden fields, HTTP bodies, or database access.
OBSERVE_JS = r"""() => {
 const visible = e => { const r=e.getBoundingClientRect(), s=getComputedStyle(e); return r.width>0 && r.height>0 && s.visibility!=='hidden' && s.display!=='none' && !e.closest('[hidden],[aria-hidden="true"]'); };
 const nodes=Array.from(document.querySelectorAll('input:not([type=hidden]),select,button,a,output,h1,h2,h3,p,label,[role],td'));
 return nodes.filter(visible).slice(0,180).map(e=>{
  let label=(e.labels?.[0]?.innerText || e.getAttribute('aria-label') || '').trim();
  let row=e.closest('tr'); let anchor=row?.querySelector('td')?.innerText?.trim() || '';
  return {tag:e.tagName.toLowerCase(), text:(e.innerText||'').trim().slice(0,500),label,
   name:e.getAttribute('name'),id:e.id||null,placeholder:e.getAttribute('placeholder'),
   role:e.getAttribute('role'),type:e.getAttribute('type'),anchor,
   value:e.type==='password'?'[REDACTED]':(('value' in e)?String(e.value):null),
   options:e.tagName==='SELECT'?Array.from(e.options).map(o=>o.label):null};
 });
}"""

HUMAN_JS = r"""(() => {
 for (const type of ['click','change','keydown']) document.addEventListener(type, e=>{
   if(!e.isTrusted || (type==='keydown' && !['Tab','Enter','Escape','ArrowDown','ArrowUp'].includes(e.key))) return;
   const t=e.target; window.__arHuman?.({type, tag:t.tagName?.toLowerCase(), identity:(t.labels?.[0]?.innerText||t.getAttribute?.('aria-label')||t.innerText||t.name||'').trim().slice(0,100)});
 }, true);
})()"""


def convert(raw: str, conversion: str):
    raw = raw.strip()
    if conversion == "text":
        return raw
    if conversion == "integer":
        if not re.fullmatch(r"[+-]?\d+", raw):
            raise AutomationError("OUTPUT_CONVERSION_FAILED")
        return int(raw)
    if conversion == "currency":
        # Deliberately US currency only; reject text contamination and other locales.
        if not re.fullmatch(r"\$?-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{2})?", raw):
            raise AutomationError("OUTPUT_CONVERSION_FAILED")
        raw = raw.replace("$", "").replace(",", "")
    try:
        number = Decimal(raw)
        if not number.is_finite():
            raise InvalidOperation
        return format(number, ".2f" if conversion == "currency" else "f")
    except InvalidOperation as exc:
        raise AutomationError("OUTPUT_CONVERSION_FAILED") from exc


class BrowserSurface:
    def __init__(self, config: Config, evidence, owner=lambda: "AUTOMATION"):
        self.config = config
        self.policy = Policy(config.policy)
        self.evidence = evidence
        self.owner = owner
        self.refs: dict[str, Target] = {}
        self.blocked = None
        self.dialog = None
        self.pw = self.browser = self.context = self.page = None

    async def start(self, record_video_dir: Path | None = None):
        self.pw = await async_playwright().start()
        self.browser = await self.pw.chromium.launch(headless=self.config.headless)
        context_kwargs = {"viewport": {"width": 1200, "height": 1000}, "service_workers": "block"}
        if record_video_dir is not None:
            record_video_dir.mkdir(parents=True, exist_ok=True)
            context_kwargs["record_video_dir"] = str(record_video_dir)
            context_kwargs["record_video_size"] = {"width": 1200, "height": 1000}
        self.context = await self.browser.new_context(**context_kwargs)
        self.context.set_default_timeout(self.config.execution.action_timeout_seconds * 1000)
        await self.context.route("**/*", self._request)
        await self.context.expose_binding("__arHuman", self._human)
        await self.context.add_init_script(HUMAN_JS)
        self.context.on("page", self._new_page)
        self.page = await self.context.new_page()

    async def _request(self, route):
        url = route.request.url
        resource = route.request.resource_type
        try:
            self.policy.url(url)
        except (AutomationError, ValueError):
            # Humans may visit/submit non-allowlisted same-origin paths (e.g. Confirm creation → /commit).
            if self.owner() == "HUMAN" and self._same_origin(url):
                await route.continue_()
                return
            # Drop third-party assets quietly; do not poison the run with POLICY_ROUTE_BLOCKED.
            if resource in {"stylesheet", "font", "image", "media", "script", "ping"} and not self._same_origin(
                url
            ):
                await route.abort()
                return
            self.blocked = "POLICY_ROUTE_BLOCKED"
            await route.abort()
        else:
            await route.continue_()

    def _same_origin(self, url: str) -> bool:
        parsed = urlsplit(url)
        if parsed.username or parsed.password:
            return False
        origin = (
            parsed.scheme,
            parsed.hostname,
            parsed.port or (443 if parsed.scheme == "https" else 80),
        )
        path = parsed.path or "/"
        return origin == self.policy.origin and ".." not in path.split("/")

    def _new_page(self, page):
        page.on("dialog", lambda dialog: setattr(self, "dialog", dialog))
        page.on("framenavigated", self._navigation)
        if self.page is not None and page != self.page:
            self.blocked = "UNEXPECTED_POPUP"

    def _navigation(self, frame):
        if self.owner() == "HUMAN":
            self.evidence.event(
                "human_navigation",
                owner="HUMAN",
                frame="frame",
                route=urlsplit(frame.url).path
                if urlsplit(frame.url).path in self.config.policy.allowed_routes
                else "[REDACTED]",
            )

    async def _human(self, source, event):
        if self.owner() != "HUMAN":
            return
        if event.get("type") not in {"click", "change", "keydown"}:
            return
        identity = event.get("identity", "")
        approved = set(
            self.config.policy.safe_click_labels
            + self.config.policy.safe_field_names
            + [
                "Restore session",
                "Resolve verification",
                "Confirm transfer",
                "Confirm create",
                "Confirm delete",
                "Confirm creation",
            ]
        )
        self.evidence.event(
            "human_activity",
            owner="HUMAN",
            action=event.get("type"),
            tag=event.get("tag"),
            target=identity if identity in approved else "[REDACTED]",
        )

    def assert_owner(self):
        if self.owner() != "AUTOMATION":
            raise AutomationError("CONTROL_NOT_OWNED")
        if self.blocked:
            code, self.blocked = self.blocked, None
            raise AutomationError(code)
        if self.dialog:
            raise AutomationError("UNEXPECTED_DIALOG")
        if self.context and len(self.context.pages) != 1:
            raise AutomationError("UNEXPECTED_POPUP")

    async def resume_ready(self):
        if not self.page or self.page.is_closed() or self.dialog or len(self.context.pages) != 1:
            return False
        self.blocked = None
        try:
            for frame in self.page.frames:
                url = frame.url or ""
                if not url.startswith("http"):
                    # about:blank / chrome-error after an aborted commit — human must leave first.
                    if url.startswith("chrome-error:") or url.startswith("chrome-untrusted:"):
                        return False
                    continue
                try:
                    self.policy.url(url)
                except (AutomationError, ValueError):
                    # Human may finish on irreversible commit routes; allow resume from there.
                    path = urlsplit(url).path or "/"
                    if not self._same_origin(url) or path not in {
                        "/commit",
                        "/transfer-commit",
                        "/create-commit",
                        "/delete-commit",
                    }:
                        return False
        except (AutomationError, ValueError):
            return False
        return True

    def left_confirmation_review(self):
        """True once no frame is still on a Confirm* review screen."""
        from .policy import CONFIRMATION_REVIEW_PATHS

        if not self.page:
            return False
        for frame in self.page.frames:
            url = frame.url or ""
            if not url.startswith("http"):
                continue
            if urlsplit(url).path in CONFIRMATION_REVIEW_PATHS:
                return False
        return True

    async def close(self):
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.pw:
            await self.pw.stop()

    async def verify_application(self):
        marker = self.page.get_by_role("heading", name=self.config.startup_text, exact=True)
        try:
            await marker.wait_for(state="visible")
        except Exception as exc:
            raise AutomationError("INCOMPATIBLE_APPLICATION_UI") from exc
        if await marker.count() != 1:
            raise AutomationError("INCOMPATIBLE_APPLICATION_UI")

    def _locate(self, root, spec: Locator, inputs, variables):
        text = str(spec.text.resolve(inputs, variables)) if spec.text else ""
        if spec.strategy == "role":
            return root.get_by_role(spec.role, name=text, exact=True)
        if spec.strategy == "label":
            return root.get_by_label(text, exact=True)
        if spec.strategy == "text":
            return root.get_by_text(text, exact=True)
        if spec.strategy == "attribute":
            return root.locator(f"[{spec.name}={json.dumps(spec.value)}]")
        row = root.locator("tr").filter(has=root.get_by_text(text, exact=True))
        if spec.child_role:
            args = (
                {"name": str(spec.child_name.resolve(inputs, variables)), "exact": True}
                if spec.child_name
                else {}
            )
            return row.get_by_role(spec.child_role, **args)
        return row.locator(spec.child_tag)

    async def resolve_target(self, target: Target, inputs: dict, variables: dict):
        frame = self.page.main_frame
        for segment in target.frame_path:
            locator = self._locate(frame, segment, inputs, variables)
            count = await locator.count()
            if count != 1:
                raise AutomationError("AMBIGUOUS_TARGET" if count > 1 else "TARGET_NOT_FOUND")
            handle = await locator.element_handle()
            frame = await handle.content_frame()
            if frame is None:
                raise AutomationError("FRAME_NOT_FOUND")
        root = self._locate(frame, target.scope, inputs, variables) if target.scope else frame
        if target.scope and await root.count() != 1:
            raise AutomationError("AMBIGUOUS_TARGET")
        locator = self._locate(root, target.locator, inputs, variables)
        count = await locator.count()
        if count != 1:
            raise AutomationError("AMBIGUOUS_TARGET" if count > 1 else "TARGET_NOT_FOUND")
        return locator

    async def _frame_path(self, frame):
        path = []
        while frame.parent_frame:
            element = await frame.frame_element()
            name = await element.get_attribute("name")
            title = await element.get_attribute("title")
            if name:
                path.insert(0, Locator(strategy="attribute", name="name", value=name))
            elif title:
                path.insert(0, Locator(strategy="attribute", name="title", value=title))
            else:
                return None
            frame = frame.parent_frame
        return path

    def _candidate(self, node, frame_path):
        tag, text = node["tag"], node["text"]
        role = node["role"] or {
            "a": "link",
            "button": "button",
            "h1": "heading",
            "h2": "heading",
            "h3": "heading",
        }.get(tag)
        approved = set(self.config.policy.approved_literals + self.config.policy.safe_click_labels)
        if node["label"]:
            # Labels must be known field names; raw values are never identifying labels.
            if node["label"] not in approved and node["label"] not in self.config.policy.safe_field_names:
                return None
            spec = Locator(strategy="label", text=literal(node["label"]))
        elif role and text:
            if text not in approved:
                return None
            spec = Locator(strategy="role", role=role, text=literal(text))
        elif tag in {"input", "select"} and node["anchor"]:
            if node["anchor"] not in approved and node["anchor"] not in self.config.policy.safe_field_names:
                return None
            spec = Locator(strategy="anchored", text=literal(node["anchor"]), child_tag=tag)
        elif tag == "output" and node["anchor"]:
            if node["anchor"] not in approved and node["anchor"] not in self.config.policy.safe_field_names:
                return None
            spec = Locator(strategy="anchored", text=literal(node["anchor"]), child_tag="output")
        elif text:
            # Never mint e-refs for dynamic values (amounts, IDs); those are not durable locators.
            if text not in approved:
                return None
            spec = Locator(strategy="text", text=literal(text))
        else:
            return None
        return Target(
            frame_path=frame_path, locator=spec, description="Visible control identified during discovery"
        )

    async def observe(self):
        self.assert_owner()
        self.refs = {}
        frames = []
        for frame in self.page.frames:
            if not frame.url.startswith("http"):
                continue
            self.policy.url(frame.url)
            frame_path = await self._frame_path(frame)
            if frame_path is None:
                continue
            nodes = await frame.evaluate(OBSERVE_JS)
            visible = []
            for node in nodes:
                candidate = self._candidate(node, frame_path)
                ref = None
                if candidate:
                    try:
                        control = await self.resolve_target(candidate, {}, {})
                        if await control.is_visible():
                            ref = f"e{len(self.refs) + 1}"
                            self.refs[ref] = candidate
                    except AutomationError:
                        pass
                visible.append(
                    {"ref": ref, **{k: node[k] for k in ["tag", "text", "label", "value", "options"]}}
                )
            frames.append(
                {
                    "path": [s.model_dump(mode="json") for s in frame_path],
                    "route": urlsplit(frame.url).path,
                    "elements": visible,
                }
            )
        screenshot = base64.b64encode(await self.page.screenshot()).decode()
        return {"frames": frames, "screenshot": screenshot}

    async def capture_sanitized_evidence(self):
        # Read-only during pause. Only structural tags and approved labels survive.
        approved = set(self.config.policy.approved_literals + self.config.policy.safe_click_labels)
        approved.update(
            [
                "Member not found",
                "Account not found",
                "Invalid member ID",
                "Invalid nickname",
                "Invalid amount",
                "Invalid member draft",
                "Permission denied",
                "Session expired",
                "Temporary service failure",
                "Maintenance notice",
                "Unexpected verification required",
                "Confirm transfer",
                "Confirm create",
                "Confirm delete",
                "Confirm creation",
                "Insufficient funds",
                "Invalid account combination",
                "Member already exists",
                "Confirmation reference",
            ]
        )
        frames = []
        for frame in self.page.frames:
            try:
                nodes = await frame.evaluate(OBSERVE_JS)
                frames.append(
                    {
                        "route": urlsplit(frame.url).path
                        if urlsplit(frame.url).path in self.config.policy.allowed_routes
                        else "[REDACTED]",
                        "controls": [
                            {
                                "tag": n["tag"],
                                "label": n["label"] if n["label"] in approved else "[REDACTED]",
                                "text": n["text"] if n["text"] in approved else "[REDACTED]",
                            }
                            for n in nodes
                        ],
                    }
                )
            except Exception:
                frames.append({"state": "unavailable"})
        return {"frames": frames, "native_dialog": bool(self.dialog)}

    async def evaluate_condition(self, condition, targets, inputs, variables):
        kind = condition.kind
        if kind in {"all", "any", "not"}:
            results = [
                await self.evaluate_condition(c, targets, inputs, variables) for c in condition.conditions
            ]
            return all(results) if kind == "all" else any(results) if kind == "any" else not results[0]
        if kind == "route":
            route = str(condition.value.resolve(inputs, variables))
            self.policy.route(route)
            return any(urlsplit(f.url).path == route for f in self.page.frames)
        if kind == "variable_equals":
            return variables.get(condition.variable) == condition.value.resolve(inputs, variables)
        try:
            control = await self.resolve_target(targets[condition.target], inputs, variables)
            if not await control.is_visible():
                return False
            if kind == "visible":
                return True
            actual = await control.inner_text() if kind == "text_equals" else await control.input_value()
            return actual.strip() == str(condition.value.resolve(inputs, variables))
        except AutomationError as exc:
            if exc.code in {"TARGET_NOT_FOUND", "FRAME_NOT_FOUND"}:
                return False
            raise

    async def extract_value(self, step, targets, inputs, variables):
        control = await self.resolve_target(targets[step.target], inputs, variables)
        raw = None
        if step.source == "text":
            raw = await control.inner_text()
        else:
            try:
                raw = await control.input_value()
            except Exception:
                # <output> and other non-inputs are common review targets; fall back to text.
                raw = await control.inner_text()
        self.evidence.sanitizer.add(raw)
        value = convert(raw, step.conversion)
        self.evidence.sanitizer.add(value)
        return value

    async def execute_action(self, step, targets, inputs, variables):
        self.assert_owner()
        self.policy.action(step.action)
        if step.action == "navigate":
            await self.page.goto(
                self.policy.route(str(step.route.resolve(inputs, variables))), wait_until="domcontentloaded"
            )
        elif step.action in {"assert", "wait_for"}:
            deadline = asyncio.get_running_loop().time() + (
                self.config.execution.action_timeout_seconds if step.action == "wait_for" else 0
            )
            while not await self.evaluate_condition(step.condition, targets, inputs, variables):
                if asyncio.get_running_loop().time() >= deadline:
                    raise AutomationError("CHECKPOINT_FAILED")
                await asyncio.sleep(0.1)
        elif step.action == "extract":
            variables[step.variable] = await self.extract_value(step, targets, inputs, variables)
        elif step.action == "scroll":
            if step.target:
                control = await self.resolve_target(targets[step.target], inputs, variables)
                await control.evaluate("(e,dy)=>e.scrollBy(0,dy)", step.delta_y)
            else:
                await self.page.mouse.wheel(0, step.delta_y)
        else:
            control = await self.resolve_target(targets[step.target], inputs, variables)
            identity = await control.evaluate(
                "e => (e.labels?.[0]?.innerText || e.getAttribute('aria-label') || ((e.tagName==='INPUT'||e.tagName==='SELECT')?e.name:e.innerText)||'').trim()"
            )
            self.policy.control(step.action, identity, getattr(step, "key", None))
            if step.action == "click":
                href = await control.get_attribute("href")
                if href:
                    from urllib.parse import urljoin

                    self.policy.url(urljoin(await control.evaluate("e=>e.ownerDocument.URL"), href))
                form_action = await control.evaluate("e => e.form?.action || null")
                if form_action:
                    self.policy.url(form_action)
                await control.click()
            elif step.action == "fill":
                await control.fill(str(step.value.resolve(inputs, variables)))
            elif step.action == "select":
                await control.select_option(label=str(step.value.resolve(inputs, variables)))
            elif step.action == "press":
                await control.press(step.key)
        self.assert_owner()
