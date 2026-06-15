import asyncio

from fastmcp import Client

from bridge_mcp.airtable import TableSchema
from bridge_mcp.config import Config
from bridge_mcp.server import build_server

RECORDS = [
    {"id": "rec1", "fields": {"Name": "Ada Lovelace", "Company": "Engines", "Sector": "Deep Tech"}},
    {"id": "rec2", "fields": {"Name": "Grace Hopper", "Company": "Compilers", "Sector": "Dev Tools"}},
]


class FakeAirtable:
    """Duck-typed stand-in for AirtableClient (no network)."""

    def __init__(self, records):
        self._records = records
        self._by_id = {r["id"]: r for r in records}

    def get_schema(self, force: bool = False):
        return TableSchema(
            id="tbl1",
            name="Participants",
            primary_field_name="Name",
            fields=[
                {"id": "f1", "name": "Name", "type": "singleLineText", "description": None},
                {"id": "f2", "name": "Company", "type": "singleLineText", "description": None},
                {"id": "f3", "name": "Sector", "type": "singleLineText", "description": None},
            ],
        )

    def get_records(self, force: bool = False):
        return self._records

    def get_record(self, record_id):
        return self._by_id.get(record_id)

    def record_url(self, record_id):
        return f"https://airtable.com/app/tbl1/{record_id}"


DUMMY_CONFIG = Config(
    api_key="x",
    base_id="appX",
    table_name=None,
    view=None,
    cache_ttl_seconds=300,
    auth_token=None,
    host="0.0.0.0",
    port=8000,
)


def make_server():
    return build_server(DUMMY_CONFIG, client=FakeAirtable(RECORDS))


def call(tool, args):
    mcp = make_server()

    async def run():
        async with Client(mcp) as client:
            return await client.call_tool(tool, args)

    return asyncio.run(run())


def test_tools_are_registered():
    mcp = make_server()

    async def run():
        async with Client(mcp) as client:
            tools = await client.list_tools()
            return {t.name for t in tools}

    names = asyncio.run(run())
    assert {"search", "fetch", "list_participants", "describe_table"} <= names


def test_search_returns_chatgpt_shape():
    result = call("search", {"query": "Grace"})
    data = result.data
    assert "results" in data
    assert data["results"][0]["id"] == "rec2"
    assert set(data["results"][0]) == {"id", "title", "url", "text"}


def test_fetch_returns_full_profile():
    result = call("fetch", {"id": "rec1"})
    data = result.data
    assert data["id"] == "rec1"
    assert data["title"] == "Ada Lovelace"
    assert "Company: Engines" in data["text"]
    assert data["url"].endswith("rec1")
    assert set(data) >= {"id", "title", "text", "url", "metadata"}


def test_fetch_unknown_id_errors():
    import pytest

    with pytest.raises(Exception, match="No participant found"):
        call("fetch", {"id": "nope"})


def test_list_participants():
    data = call("list_participants", {}).data
    assert data["total"] == 2
    assert {p["name"] for p in data["participants"]} == {"Ada Lovelace", "Grace Hopper"}


def test_describe_table():
    data = call("describe_table", {}).data
    assert data["primary_field"] == "Name"
    assert {f["name"] for f in data["fields"]} == {"Name", "Company", "Sector"}
