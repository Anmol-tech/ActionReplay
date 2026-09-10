"""Synthetic demo application. The agent gets no access to this state or scenario setup."""

import asyncio
import html
import os
from urllib.parse import urlencode
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

MEMBERS = {
    "00123": {"savings": "1,250.45", "checking": "420.10"},
    "00678": {"savings": "9,876.54", "checking": "85.00"},
    "00999": {"checking": "75.20"},
}


def create_app(scenario=None):
    app = FastAPI()
    scenario = scenario or os.getenv("ACTIONREPLAY_SCENARIO", "normal")
    sessions = {}

    @app.middleware("http")
    async def session(request, call_next):
        sid = request.cookies.get("demo_session", "")
        if sid not in sessions:
            sid = uuid4().hex
            sessions[sid] = {"restored": False, "continued": False, "transient_seen": False}
        request.state.session = sessions[sid]
        response = await call_next(request)
        response.set_cookie("demo_session", sid, httponly=True, samesite="strict")
        return response

    def page(body, title="LegacyBank 1.0"):
        return HTMLResponse(f"""<!doctype html><html><head><title>{title}</title><style>
        body{{font:16px Georgia;background:#f4f1e8;color:#172c38;margin:24px}}
        table{{border-collapse:collapse;width:90%;background:white}}td,th{{border:1px solid #bac4c8;padding:12px}}
        button,a,input,select{{font:inherit;margin:5px;padding:7px}}h1{{font-size:25px}}iframe{{width:98%;height:670px;border:1px solid #bac4c8}}
        .status{{padding:16px;background:#fff4cf}}output{{font-weight:bold}}</style></head><body>{body}</body></html>""")

    def query(request):
        return dict(request.query_params)

    @app.get("/", response_class=HTMLResponse)
    async def home():
        return page(
            '<h1>LegacyBank 1.0 — Staff workspace</h1><iframe name="shell" title="Bank shell" src="/shell"></iframe>'
        )

    @app.get("/shell", response_class=HTMLResponse)
    async def shell():
        return page('<iframe name="workspace" title="Workspace" src="/workspace"></iframe>')

    @app.get("/workspace", response_class=HTMLResponse)
    async def workspace():
        return page(
            """<h2>Member servicing</h2><form action="/search"><table><tr><td><label for="member">Member ID</label></td><td><input id="member" name="member_id" autocomplete="off"></td></tr></table><button>Search</button></form>"""
        )

    @app.get("/search", response_class=HTMLResponse)
    async def search(request: Request):
        q = query(request)
        member = q.get("member_id", "")
        state = request.state.session
        if not member.isdigit() or len(member) != 5:
            return page('<p class="status">Invalid member ID</p><a href="/workspace">Back</a>')
        if scenario == "permission":
            return page('<p class="status">Permission denied</p>')
        if scenario == "session" and not state["restored"]:
            return page(
                '<p class="status">Session expired</p><p>Operator: restore the synthetic session, then Resume in ActionReplay.</p><a href="/restore?'
                + urlencode(q)
                + '">Restore session</a>'
            )
        if scenario == "transient" and not state["transient_seen"]:
            state["transient_seen"] = True
            return page(
                '<p class="status">Temporary service failure</p><a href="/search?'
                + urlencode(q)
                + '">Continue</a>'
            )
        if scenario == "interstitial" and not state["continued"]:
            return page(
                '<p class="status">Maintenance notice</p><a href="/continue?'
                + urlencode(q)
                + '">Continue</a>'
            )
        if scenario == "slow":
            await asyncio.sleep(1.5)
        if scenario == "dialog" and not state["continued"]:
            return page(
                '<dialog open><p>Unexpected verification required</p><a href="/continue?'
                + urlencode(q)
                + '">Resolve verification</a></dialog>'
            )
        if member not in MEMBERS:
            return page('<p class="status">Member not found</p><a href="/workspace">Back</a>')
        return page(
            f'<h2>Search results</h2><table><tr><th>Member</th><th>Action</th></tr><tr><td>{html.escape(member)}</td><td><a href="/member?{urlencode(q)}">Open member</a></td></tr></table>'
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
        member_id = request.query_params.get("member_id", "")
        if member_id not in MEMBERS:
            return page("<p>Member not found</p>")
        rows = "".join(
            f'<tr><td>{a.title()}</td><td><a href="/account?{urlencode(dict(member_id=member_id, account_type=a))}">{a.title()}</a></td></tr>'
            for a in MEMBERS[member_id]
        )
        return page(
            f'<h2>Member details</h2><p>Member {html.escape(member_id)}</p><table>{rows}</table><a href="/new?{urlencode(dict(member_id=member_id))}">Prepare sub-account</a>'
        )

    @app.get("/account", response_class=HTMLResponse)
    async def account(request: Request):
        q = query(request)
        account_type = q.get("account_type", "savings")
        amount = MEMBERS.get(q.get("member_id"), {}).get(account_type)
        if amount is None:
            return page("<p>Account not found</p>")
        return page(
            f"<h2>{html.escape(account_type.title())} balance</h2><table><tr><td>Amount</td><td><output>${amount}</output></td></tr></table>"
        )

    @app.get("/new", response_class=HTMLResponse)
    async def new(request: Request):
        member_id = html.escape(request.query_params.get("member_id", ""), quote=True)
        return page(
            f'''<h2>Prepare sub-account</h2><form action="/review"><input type="hidden" name="member_id" value="{member_id}"><table><tr><td>Account type</td><td><select name="account_type"><option>Savings</option><option>Checking</option></select></td></tr><tr><td><label for="nickname">Nickname</label></td><td><input id="nickname" name="nickname"></td></tr></table><button>Review</button></form>'''
        )

    @app.get("/review", response_class=HTMLResponse)
    async def review(request: Request):
        q = query(request)
        if not q.get("nickname", "").strip():
            return page("<p>Invalid nickname</p>")
        return page(
            f"""<h2>Sub-account review</h2><table><tr><td>Account type:</td><td><output>{html.escape(q.get("account_type", ""))}</output></td></tr><tr><td>Nickname:</td><td><output>{html.escape(q.get("nickname", ""))}</output></td></tr></table><form action="/commit" method="post"><button>Confirm creation</button></form>"""
        )

    @app.post("/commit")
    async def commit():
        return page("<p>Synthetic submission reached</p>")

    return app


app = create_app()
