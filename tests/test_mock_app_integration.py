import httpx
import pytest

from actionreplay.mock_app import create_app


@pytest.fixture
def transport():
    return lambda app: httpx.ASGITransport(app=app)


async def client_for(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://bank")


@pytest.mark.asyncio
async def test_app_instances_are_isolated():
    first, second = create_app(), create_app()
    async with await client_for(first) as a, await client_for(second) as b:
        await a.get("/create-review?new_member_id=00444&display_name=New%20Member")
        await a.post("/create-commit")
        assert "Member not found" not in (await a.get("/search?member_id=00444")).text
        assert "Member not found" in (await b.get("/search?member_id=00444")).text


@pytest.mark.asyncio
async def test_subaccount_preserves_primary_balance_and_renders():
    app = create_app()
    async with await client_for(app) as client:
        before = (await client.get("/account?member_id=00123&account_type=savings")).text
        await client.get("/review?member_id=00123&account_type=Savings&nickname=Holiday")
        await client.post("/commit")
        member = (await client.get("/member?member_id=00123")).text
        after = (await client.get("/account?member_id=00123&account_type=savings")).text
        assert "Holiday" in member and "$1,250.45" in before and "$1,250.45" in after


@pytest.mark.asyncio
async def test_transfer_updates_both_accounts_and_activity():
    app = create_app()
    async with await client_for(app) as client:
        await client.get("/transfer-review?member_id=00123&from_account=Savings&to_account=Checking&amount=25.00")
        response = await client.post("/transfer-commit")
        assert "Confirmation reference" in (await client.get(response.headers["location"])).text
        savings = (await client.get("/account?member_id=00123&account_type=savings")).text
        checking = (await client.get("/account?member_id=00123&account_type=checking")).text
        assert "$1,225.45" in savings and "$445.10" in checking
        assert "Transfer to Checking" in savings and "Transfer from Savings" in checking


@pytest.mark.asyncio
async def test_invalid_transfer_and_duplicate_create_are_visible():
    app = create_app()
    async with await client_for(app) as client:
        assert "Insufficient funds" in (await client.get("/transfer-review?member_id=00123&from_account=Checking&to_account=Savings&amount=99999")).text
        assert "Invalid account combination" in (await client.get("/transfer-review?member_id=00123&from_account=Savings&to_account=Savings&amount=1")).text
        assert "Member already exists" in (await client.get("/create-review?new_member_id=00123&display_name=Duplicate")).text
        assert "Member not found" in (await client.get("/review?member_id=00000&account_type=Savings&nickname=X")).text


@pytest.mark.asyncio
async def test_sensitive_flows_open_without_staff_gate():
    app = create_app()
    async with await client_for(app) as client:
        transfer = (await client.get("/transfer?member_id=00123")).text
        create = (await client.get("/create-member")).text
        delete = (await client.get("/delete-member?member_id=00123")).text
        for body in (transfer, create, delete):
            assert "Staff verification required" not in body
            assert "Verify staff authorization" not in body
        assert "Transfer funds" in transfer
        assert "Create member" in create
        assert "Delete member" in delete


@pytest.mark.asyncio
async def test_bank_pages_use_normal_customer_facing_language():
    app = create_app()
    async with await client_for(app) as client:
        pages = [
            (await client.get("/workspace")).text,
            (await client.get("/create-member")).text,
            (await client.get("/transfer?member_id=00123")).text,
        ]
    combined = " ".join(pages)
    lowered = combined.lower()
    for term in ("actionreplay", "automation", "live browser", "human operator", "synthetic"):
        assert term not in lowered
    assert "Transfer funds" in combined
    assert "Create member" in combined
