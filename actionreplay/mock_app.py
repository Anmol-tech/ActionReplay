"""Synthetic LegacyBank staff workstation. The agent gets no access to this ledger or scenario setup."""

from __future__ import annotations

import asyncio
import copy
import html
import os
import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse

SEED_MEMBERS = {
    "00123": {
        "name": "Jordan Hale",
        "status": "Active",
        "branch": "0142",
        "accounts": {
            "savings": {"balance": Decimal("1250.45"), "activity": []},
            "checking": {"balance": Decimal("420.10"), "activity": []},
        },
        "subaccounts": [],
    },
    "00678": {
        "name": "Samira Okonkwo",
        "status": "Active",
        "branch": "0142",
        "accounts": {
            "savings": {"balance": Decimal("9876.54"), "activity": []},
            "checking": {"balance": Decimal("85.00"), "activity": []},
        },
        "subaccounts": [],
    },
    "00999": {
        "name": "Casey Nguyen",
        "status": "Restricted",
        "branch": "0208",
        "accounts": {
            "checking": {"balance": Decimal("75.20"), "activity": []},
        },
        "subaccounts": [],
    },
}

CSS = """
:root {
  --ink:#102033; --muted:#5b6b7c; --line:#9aabba; --paper:#f2eee4;
  --panel:#fffdf8; --navy:#0c2d4a; --navy-2:#163f63; --accent:#1f6f5b;
  --warn:#8a5a12; --warn-bg:#fff2d6; --danger:#7a2430; --ok:#1f6f5b;
}
*{box-sizing:border-box}
body{
  margin:0; color:var(--ink);
  font:15px/1.45 "Avenir Next", "Segoe UI", "Helvetica Neue", sans-serif;
  background:
    linear-gradient(180deg, #d9e2ea 0 48px, transparent 48px),
    repeating-linear-gradient(0deg, transparent, transparent 23px, rgba(12,45,74,.04) 24px),
    var(--paper);
}
.topbar{
  background:linear-gradient(180deg, var(--navy-2), var(--navy));
  color:#e8eef4; padding:10px 16px; display:flex; gap:18px; align-items:center;
  border-bottom:3px solid #c4a35a; font-family: ui-monospace, "Menlo", "Consolas", monospace; font-size:12px;
}
.topbar strong{font-size:13px; letter-spacing:.04em}
.brand-wrap{padding:18px 20px 8px}
h1{margin:0; font-size:24px; color:var(--navy); letter-spacing:.01em}
h2{margin:0 0 12px; font-size:20px; color:var(--navy)}
.shell-frame, .workspace-frame{
  width:calc(100% - 32px); margin:0 16px 16px; border:1px solid var(--line);
  background:var(--panel); box-shadow:0 1px 0 rgba(16,32,51,.08);
}
.shell-frame{height:720px}
.workspace-frame{height:640px; width:calc(100% - 24px); margin:12px}
.panel{padding:18px 20px 28px; max-width:920px}
.meta{
  display:flex; flex-wrap:wrap; gap:10px 18px; margin:0 0 16px; color:var(--muted);
  font-family: ui-monospace, "Menlo", "Consolas", monospace; font-size:12px;
}
.meta span{background:#e7eef4; border:1px solid #c5d2de; padding:3px 8px}
table{border-collapse:collapse; width:100%; background:var(--panel); margin:10px 0 14px}
th,td{border:1px solid var(--line); padding:10px 12px; text-align:left; vertical-align:top}
th{background:#e7eef4; font-size:13px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted)}
button,a.button{font:inherit}
button, .button{
  font:inherit; margin:4px 6px 4px 0; padding:7px 12px; cursor:pointer;
  background:linear-gradient(180deg,#f7fafc,#d9e3ec); border:1px solid #7f93a5; color:var(--ink);
}
button.primary, a.button.primary{
  background:linear-gradient(180deg,#2a7d68,#1f6f5b); border-color:#155445; color:#fff;
}
a{color:#0f4f7a}
input,select{
  font:inherit; padding:7px 9px; border:1px solid #7f93a5; background:#fff; min-width:180px;
}
label{font-weight:500}
.status{
  padding:12px 14px; background:var(--warn-bg); border:1px solid #e0c48a; color:var(--warn);
  margin:0 0 14px;
}
.status.ok{background:#e5f4ee; border-color:#9ccbb8; color:var(--ok)}
.status.bad{background:#f8e8ea; border-color:#d8a0a8; color:var(--danger)}
output{font-weight:700; font-family: ui-monospace, "Menlo", "Consolas", monospace}
.actions{margin-top:12px}
.note{color:var(--muted); font-size:13px; margin:8px 0 0}
.dossier{display:grid; grid-template-columns:1.2fr .8fr; gap:14px}
@media (max-width:800px){.dossier{grid-template-columns:1fr}}
.card{
  border:1px solid var(--line); background:#fff; padding:12px 14px;
}
.card h3{margin:0 0 8px; font-size:14px; text-transform:uppercase; letter-spacing:.05em; color:var(--muted)}
"""


def money(value: Decimal) -> str:
    quantized = value.quantize(Decimal("0.01"))
    sign = "-" if quantized < 0 else ""
    body = f"{abs(quantized):,.2f}"
    return f"{sign}${body}"


def parse_amount(raw: str) -> Decimal | None:
    text = (raw or "").strip().replace("$", "").replace(",", "")
    if not re.fullmatch(r"-?\d+(?:\.\d{1,2})?", text):
        return None
    try:
        return Decimal(text).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def create_app(scenario=None):
    app = FastAPI()
    scenario = scenario or os.getenv("ACTIONREPLAY_SCENARIO", "normal")
    members = copy.deepcopy(SEED_MEMBERS)
    sessions = {}
    refs = {"n": 1000}

    def next_ref(prefix: str) -> str:
        refs["n"] += 1
        return f"{prefix}-{refs['n']}"

    @app.middleware("http")
    async def session(request, call_next):
        sid = request.cookies.get("demo_session", "")
        if sid not in sessions:
            sid = uuid4().hex
            sessions[sid] = {
                "restored": False,
                "continued": False,
                "transient_seen": False,
                "drafts": {},
                "flash": None,
            }
        request.state.session = sessions[sid]
        response = await call_next(request)
        response.set_cookie("demo_session", sid, httponly=True, samesite="strict")
        return response

    def page(body, title="LegacyBank 1.0", chrome=True):
        bar = ""
        if chrome:
            bar = """<div class="topbar">
              <strong>LBCORE · TELLER</strong>
            </div>"""
        return HTMLResponse(
            f"""<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(title)}</title>
            <style>{CSS}</style></head><body>{bar}{body}</body></html>"""
        )

    def query(request):
        return dict(request.query_params)

    def flash_html(request):
        flash = request.state.session.pop("flash", None)
        if not flash:
            return ""
        kind, text = flash
        cls = "ok" if kind == "ok" else "bad" if kind == "bad" else ""
        return f'<p class="status {cls}">{html.escape(text)}</p>'

    def set_flash(request, kind, text):
        request.state.session["flash"] = (kind, text)

    def require_member(request):
        member_id = request.query_params.get("member_id", "")
        if member_id not in members:
            return None, page('<div class="panel"><p class="status bad">Member not found</p></div>')
        return member_id, None

    def account_type_key(label: str) -> str:
        return (label or "").strip().lower()

    @app.get("/", response_class=HTMLResponse)
    async def home():
        return page(
            """<div class="brand-wrap">
              <h1>LegacyBank 1.0 — Staff workspace</h1>
            </div>
            <iframe class="shell-frame" name="shell" title="Bank shell" src="/shell"></iframe>"""
        )

    @app.get("/shell", response_class=HTMLResponse)
    async def shell():
        return page(
            '<iframe class="workspace-frame" name="workspace" title="Workspace" src="/workspace"></iframe>',
            chrome=False,
        )

    @app.get("/workspace", response_class=HTMLResponse)
    async def workspace(request: Request):
        submitted = request.query_params.get("submitted", "")
        notice = flash_html(request)
        if submitted and not notice:
            notice = (
                f'<p class="status ok">Request accepted · Confirmation reference '
                f"{html.escape(submitted)}</p>"
            )
        return page(
            f"""<div class="panel">
              <h2>Member servicing</h2>
              {notice}
              <p><a href="/create-member">Create member</a></p>
              <form action="/search">
                <table>
                  <tr><td><label for="member">Member ID</label></td>
                  <td><input id="member" name="member_id" autocomplete="off"></td></tr>
                </table>
                <button>Search</button>
              </form>
            </div>"""
        )

    @app.get("/search", response_class=HTMLResponse)
    async def search(request: Request):
        q = query(request)
        member = q.get("member_id", "")
        state = request.state.session
        if not member.isdigit() or len(member) != 5:
            return page(
                '<div class="panel"><p class="status bad">Invalid member ID</p>'
                '<a href="/workspace">Back</a></div>'
            )
        if scenario == "permission":
            return page('<div class="panel"><p class="status bad">Permission denied</p></div>')
        if scenario == "session" and not state["restored"]:
            return page(
                '<div class="panel"><p class="status">Session expired</p>'
                "<p>Restore the teller session, then resume from the control console.</p>"
                f'<a href="/restore?{urlencode(q)}">Restore session</a></div>'
            )
        if scenario == "transient" and not state["transient_seen"]:
            state["transient_seen"] = True
            return page(
                '<div class="panel"><p class="status">Temporary service failure</p>'
                f'<a href="/search?{urlencode(q)}">Continue</a></div>'
            )
        if scenario == "interstitial" and not state["continued"]:
            return page(
                '<div class="panel"><p class="status">Maintenance notice</p>'
                f'<a href="/continue?{urlencode(q)}">Continue</a></div>'
            )
        if scenario == "slow":
            await asyncio.sleep(1.5)
        if scenario == "dialog" and not state["continued"]:
            return page(
                f'<div class="panel"><dialog open><p>Unexpected verification required</p>'
                f'<a href="/continue?{urlencode(q)}">Resolve verification</a></dialog></div>'
            )
        if member not in members:
            return page(
                '<div class="panel"><p class="status bad">Member not found</p>'
                '<a href="/workspace">Back</a></div>'
            )
        record = members[member]
        return page(
            f"""<div class="panel">
              <h2>Search results</h2>
              <table>
                <tr><th>Member</th><th>Name</th><th>Status</th><th>Action</th></tr>
                <tr>
                  <td>{html.escape(member)}</td>
                  <td>{html.escape(record["name"])}</td>
                  <td>{html.escape(record["status"])}</td>
                  <td><a href="/member?{urlencode(q)}">Open member</a></td>
                </tr>
              </table>
              <a href="/workspace">Back</a>
            </div>"""
        )

    @app.get("/restore")
    async def restore(request: Request):
        request.state.session["restored"] = True
        return await search(request)

    @app.get("/continue")
    async def continue_(request: Request):
        request.state.session["continued"] = True
        return await search(request)

    @app.get("/member", response_class=HTMLResponse)
    async def member(request: Request):
        member_id, error = require_member(request)
        if error:
            return error
        record = members[member_id]
        rows = "".join(
            f'<tr><td>{a.title()}</td><td><output>{money(info["balance"])}</output></td>'
            f'<td><a href="/account?{urlencode(dict(member_id=member_id, account_type=a))}">{a.title()}</a></td></tr>'
            for a, info in record["accounts"].items()
        )
        subs = "".join(
            f"<tr><td>{html.escape(s['type'])}</td><td>{html.escape(s['nickname'])}</td>"
            f"<td>{html.escape(s['status'])}</td></tr>"
            for s in record["subaccounts"]
        ) or "<tr><td colspan='3'>None on file</td></tr>"
        q = urlencode(dict(member_id=member_id))
        return page(
            f"""<div class="panel">
              <h2>Member details</h2>
              <p>Member {html.escape(member_id)}</p>
              <div class="dossier">
                <div class="card">
                  <h3>Accounts</h3>
                  <table><tr><th>Type</th><th>Balance</th><th>Open</th></tr>{rows}</table>
                </div>
                <div class="card">
                  <h3>Sub-accounts</h3>
                  <table><tr><th>Type</th><th>Nickname</th><th>Status</th></tr>{subs}</table>
                </div>
              </div>
              <div class="actions">
                <p><a href="/new?{q}">Prepare sub-account</a></p>
                <p><a href="/transfer?{q}">Transfer funds</a></p>
                <p><a href="/delete-member?{q}">Delete member</a></p>
                <p><a href="/workspace">Back</a></p>
              </div>
            </div>"""
        )

    @app.get("/account", response_class=HTMLResponse)
    async def account(request: Request):
        q = query(request)
        account_type = account_type_key(q.get("account_type", "savings"))
        record = members.get(q.get("member_id", ""))
        info = record["accounts"].get(account_type) if record else None
        if info is None:
            return page('<div class="panel"><p class="status bad">Account not found</p></div>')
        amount = money(info["balance"])
        activity = "".join(
            f"<tr><td>{html.escape(row['when'])}</td><td>{html.escape(row['memo'])}</td>"
            f"<td><output>{html.escape(row['amount'])}</output></td></tr>"
            for row in info["activity"][-8:]
        ) or "<tr><td colspan='3'>No recent activity</td></tr>"
        return page(
            f"""<div class="panel">
              <h2>{html.escape(account_type.title())} balance</h2>
              <table><tr><td>Amount</td><td><output>{amount}</output></td></tr></table>
              <div class="card">
                <h3>Recent activity</h3>
                <table><tr><th>When</th><th>Memo</th><th>Amount</th></tr>{activity}</table>
              </div>
              <a href="/member?{urlencode({"member_id": q.get("member_id", "")})}">Back</a>
            </div>"""
        )

    @app.get("/new", response_class=HTMLResponse)
    async def new(request: Request):
        member_id = request.query_params.get("member_id", "")
        if member_id not in members:
            return page('<div class="panel"><p class="status bad">Member not found</p></div>')
        escaped = html.escape(member_id, quote=True)
        return page(
            f'''<div class="panel">
              <h2>Prepare sub-account</h2>
              <form action="/review">
                <input type="hidden" name="member_id" value="{escaped}">
                <table>
                  <tr><td>Account type</td>
                    <td><select name="account_type"><option>Savings</option><option>Checking</option></select></td></tr>
                  <tr><td><label for="nickname">Nickname</label></td>
                    <td><input id="nickname" name="nickname"></td></tr>
                </table>
                <button>Review</button>
              </form>
              <a href="/member?member_id={escaped}">Back</a>
            </div>'''
        )

    @app.get("/review", response_class=HTMLResponse)
    async def review(request: Request):
        q = query(request)
        member_id = q.get("member_id", "")
        nickname = (q.get("nickname") or "").strip()
        account_type = (q.get("account_type") or "").strip()
        if member_id not in members:
            return page('<div class="panel"><p class="status bad">Member not found</p></div>')
        if not nickname or account_type not in {"Savings", "Checking"}:
            return page('<div class="panel"><p class="status bad">Invalid nickname</p></div>')
        request.state.session["drafts"]["subaccount"] = {
            "member_id": member_id,
            "account_type": account_type,
            "nickname": nickname,
        }
        return page(
            f"""<div class="panel">
              <h2>Sub-account review</h2>
              <table>
                <tr><td>Account type:</td><td><output>{html.escape(account_type)}</output></td></tr>
                <tr><td>Nickname:</td><td><output>{html.escape(nickname)}</output></td></tr>
              </table>
              <form action="/commit" method="post"><button>Confirm creation</button></form>
              <a href="/new?{urlencode({"member_id": member_id})}">Back</a>
            </div>"""
        )

    @app.post("/commit")
    async def commit(request: Request):
        draft = request.state.session["drafts"].pop("subaccount", None)
        if not draft or draft["member_id"] not in members:
            set_flash(request, "bad", "No sub-account draft to commit")
            return RedirectResponse("/workspace", status_code=303)
        members[draft["member_id"]]["subaccounts"].append(
            {
                "type": draft["account_type"],
                "nickname": draft["nickname"],
                "status": "Pending open",
            }
        )
        ref = next_ref("SUB")
        set_flash(request, "ok", f"Sub-account request accepted · Confirmation reference {ref}")
        return RedirectResponse(f"/workspace?submitted={ref}", status_code=303)

    @app.get("/commit", response_class=HTMLResponse)
    async def commit_get():
        return page(
            """<div class="panel">
              <p>Confirm creation posts here from the review screen.</p>
              <p><a href="/workspace">Back to workspace</a></p>
            </div>"""
        )

    @app.get("/transfer", response_class=HTMLResponse)
    async def transfer(request: Request):
        member_id, error = require_member(request)
        if error:
            return error
        record = members[member_id]
        account_names = [a.title() for a in record["accounts"]]
        from_options = "".join(f"<option>{name}</option>" for name in account_names)
        # Default the destination to a different account when one exists.
        to_options = "".join(
            f"<option{' selected' if index == (1 if len(account_names) > 1 else 0) else ''}>{name}</option>"
            for index, name in enumerate(account_names)
        )
        escaped = html.escape(member_id, quote=True)
        review_label = "Continue to review" if scenario == "drift" else "Review transfer"
        return page(
            f'''<div class="panel">
              <h2>Transfer funds</h2>
              <form action="/transfer-review">
                <input type="hidden" name="member_id" value="{escaped}">
                <table>
                  <tr><td>From account</td><td><select name="from_account">{from_options}</select></td></tr>
                  <tr><td>To account</td><td><select name="to_account">{to_options}</select></td></tr>
                  <tr><td><label for="amount">Amount</label></td>
                    <td><input id="amount" name="amount" value="25.00"></td></tr>
                </table>
                <button>{review_label}</button>
              </form>
              <a href="/member?member_id={escaped}">Back</a>
            </div>'''
        )

    @app.get("/transfer-review", response_class=HTMLResponse)
    async def transfer_review(request: Request):
        q = query(request)
        member_id = q.get("member_id", "")
        if member_id not in members:
            return page('<div class="panel"><p class="status bad">Member not found</p></div>')
        from_account = (q.get("from_account") or "").strip()
        to_account = (q.get("to_account") or "").strip()
        amount = parse_amount(q.get("amount", ""))
        from_key, to_key = account_type_key(from_account), account_type_key(to_account)
        accounts = members[member_id]["accounts"]
        if from_key not in accounts or to_key not in accounts:
            return page('<div class="panel"><p class="status bad">Account not found</p></div>')
        if from_key == to_key:
            return page(
                '<div class="panel"><p class="status bad">Invalid account combination</p>'
                f'<a href="/transfer?{urlencode({"member_id": member_id})}">Back</a></div>'
            )
        if amount is None or amount <= 0:
            return page('<div class="panel"><p class="status bad">Invalid amount</p></div>')
        if accounts[from_key]["balance"] < amount:
            return page(
                '<div class="panel"><p class="status bad">Insufficient funds</p>'
                f'<a href="/transfer?{urlencode({"member_id": member_id})}">Back</a></div>'
            )
        request.state.session["drafts"]["transfer"] = {
            "member_id": member_id,
            "from_account": from_account,
            "to_account": to_account,
            "amount": str(amount),
        }
        return page(
            f"""<div class="panel">
              <h2>Transfer review</h2>
              <table>
                <tr><td>From account</td><td><output>{html.escape(from_account)}</output></td></tr>
                <tr><td>To account</td><td><output>{html.escape(to_account)}</output></td></tr>
                <tr><td>Amount</td><td><output>{html.escape(f"{amount:.2f}")}</output></td></tr>
              </table>
              <form action="/transfer-commit" method="post"><button>Confirm transfer</button></form>
              <a href="/transfer?{urlencode({"member_id": member_id})}">Back</a>
            </div>"""
        )

    @app.post("/transfer-commit")
    async def transfer_commit(request: Request):
        draft = request.state.session["drafts"].pop("transfer", None)
        if not draft or draft["member_id"] not in members:
            set_flash(request, "bad", "No transfer draft to commit")
            return RedirectResponse("/workspace", status_code=303)
        member_id = draft["member_id"]
        from_key = account_type_key(draft["from_account"])
        to_key = account_type_key(draft["to_account"])
        amount = Decimal(draft["amount"])
        accounts = members[member_id]["accounts"]
        if from_key not in accounts or to_key not in accounts or from_key == to_key:
            set_flash(request, "bad", "Invalid account combination")
            return RedirectResponse("/workspace", status_code=303)
        if accounts[from_key]["balance"] < amount:
            set_flash(request, "bad", "Insufficient funds")
            return RedirectResponse("/workspace", status_code=303)
        accounts[from_key]["balance"] -= amount
        accounts[to_key]["balance"] += amount
        accounts[from_key]["activity"].append(
            {
                "when": "Today",
                "memo": f"Transfer to {draft['to_account']}",
                "amount": money(-amount),
            }
        )
        accounts[to_key]["activity"].append(
            {
                "when": "Today",
                "memo": f"Transfer from {draft['from_account']}",
                "amount": money(amount),
            }
        )
        ref = next_ref("XFER")
        set_flash(request, "ok", f"Transfer posted · Confirmation reference {ref}")
        return RedirectResponse(f"/workspace?submitted={ref}", status_code=303)

    @app.get("/transfer-commit", response_class=HTMLResponse)
    async def transfer_commit_get():
        return page(
            """<div class="panel">
              <p>Confirm transfer posts here from the review screen.</p>
              <p><a href="/workspace">Back to workspace</a></p>
            </div>"""
        )

    @app.get("/create-member", response_class=HTMLResponse)
    async def create_member(request: Request):
        return page(
            """<div class="panel">
              <h2>Create member</h2>
              <form action="/create-review">
                <table>
                  <tr><td><label for="new_member_id">New member ID</label></td>
                    <td><input id="new_member_id" name="new_member_id"></td></tr>
                  <tr><td><label for="display_name">Display name</label></td>
                    <td><input id="display_name" name="display_name"></td></tr>
                </table>
                <button>Review create</button>
              </form>
              <a href="/workspace">Back</a>
            </div>"""
        )

    @app.get("/create-review", response_class=HTMLResponse)
    async def create_review(request: Request):
        q = query(request)
        mid = (q.get("new_member_id") or "").strip()
        name = (q.get("display_name") or "").strip()
        if not mid.isdigit() or len(mid) != 5 or not name:
            return page(
                "<div class='panel'><p class='status bad'>Invalid member draft</p>"
                "<a href='/create-member'>Back</a></div>"
            )
        if mid in members:
            return page(
                "<div class='panel'><p class='status bad'>Member already exists</p>"
                "<a href='/create-member'>Back</a></div>"
            )
        request.state.session["drafts"]["create"] = {"new_member_id": mid, "display_name": name}
        return page(
            f"""<div class="panel">
              <h2>Create member review</h2>
              <table>
                <tr><td>New member ID</td><td><output>{html.escape(mid)}</output></td></tr>
                <tr><td>Display name</td><td><output>{html.escape(name)}</output></td></tr>
              </table>
              <form action="/create-commit" method="post"><button>Confirm create</button></form>
              <a href="/create-member">Back</a>
            </div>"""
        )

    @app.post("/create-commit")
    async def create_commit(request: Request):
        draft = request.state.session["drafts"].pop("create", None)
        if not draft:
            set_flash(request, "bad", "No member draft to commit")
            return RedirectResponse("/workspace", status_code=303)
        mid = draft["new_member_id"]
        if mid in members:
            set_flash(request, "bad", "Member already exists")
            return RedirectResponse("/workspace", status_code=303)
        members[mid] = {
            "name": draft["display_name"],
            "status": "Active",
            "branch": "0142",
            "accounts": {
                "savings": {"balance": Decimal("0.00"), "activity": []},
                "checking": {"balance": Decimal("0.00"), "activity": []},
            },
            "subaccounts": [],
        }
        ref = next_ref("MEM")
        set_flash(request, "ok", f"Member created · Confirmation reference {ref}")
        return RedirectResponse(f"/workspace?submitted={ref}", status_code=303)

    @app.get("/create-commit", response_class=HTMLResponse)
    async def create_commit_get():
        return page(
            """<div class="panel">
              <p>Confirm create posts here from the review screen.</p>
              <p><a href="/workspace">Back to workspace</a></p>
            </div>"""
        )

    @app.get("/delete-member", response_class=HTMLResponse)
    async def delete_member(request: Request):
        member_id, error = require_member(request)
        if error:
            return error
        q = urlencode(dict(member_id=member_id))
        return page(
            f"""<div class="panel">
              <h2>Delete member</h2>
              <p class="status">This permanently closes member {html.escape(member_id)} and linked accounts.</p>
              <a href="/delete-confirm?{q}">Review delete</a>
              <a href="/member?{q}">Back</a>
            </div>"""
        )

    @app.get("/delete-confirm", response_class=HTMLResponse)
    async def delete_confirm(request: Request):
        member_id, error = require_member(request)
        if error:
            return error
        request.state.session["drafts"]["delete"] = {"member_id": member_id}
        return page(
            f"""<div class="panel">
              <h2>Delete member review</h2>
              <table><tr><td>Member:</td><td><output>{html.escape(member_id)}</output></td></tr></table>
              <form action="/delete-commit" method="post"><button>Confirm delete</button></form>
              <a href="/member?{urlencode({"member_id": member_id})}">Back</a>
            </div>"""
        )

    @app.post("/delete-commit")
    async def delete_commit(request: Request):
        draft = request.state.session["drafts"].pop("delete", None)
        if not draft or draft["member_id"] not in members:
            set_flash(request, "bad", "No delete draft to commit")
            return RedirectResponse("/workspace", status_code=303)
        del members[draft["member_id"]]
        ref = next_ref("DEL")
        set_flash(request, "ok", f"Member deleted · Confirmation reference {ref}")
        return RedirectResponse(f"/workspace?submitted={ref}", status_code=303)

    @app.get("/delete-commit", response_class=HTMLResponse)
    async def delete_commit_get():
        return page(
            """<div class="panel">
              <p>Confirm delete posts here from the review screen.</p>
              <p><a href="/workspace">Back to workspace</a></p>
            </div>"""
        )

    return app


app = create_app()
