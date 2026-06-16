import asyncio

from fastmcp import Client

from bridge_mcp.airtable import TableSchema
from bridge_mcp.config import Config
from bridge_mcp.research import ResearchResult
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


class FakeExa:
    """Duck-typed stand-in for ExaClient (no network)."""

    source = "exa"

    def __init__(self, results=None):
        self._results = (
            results
            if results is not None
            else [
                ResearchResult(
                    title="Ada in TechCrunch",
                    url="https://tc.com/ada",
                    snippet="Ada raised a seed round for Engines.",
                    published_date="2024-05-01",
                    author="Writer",
                )
            ]
        )
        self.calls = []

    def search(self, query, num_results=5):
        self.calls.append((query, num_results))
        return self._results


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


def make_server_with_exa(exa):
    return build_server(DUMMY_CONFIG, client=FakeAirtable(RECORDS), exa_client=exa)


# A record with an identifier (LinkedIn URL + a personal domain) so grounding has
# something to anchor on.
RESEARCH_RECORD = {
    "id": "rec1",
    "fields": {
        "Name": "Ada Lovelace",
        "Company": "Engines",
        "email": "ada@analyticalengines.io",
        "linkedin": "https://www.linkedin.com/in/ada-lovelace",
    },
}


def make_research_server(exa, records=None):
    return build_server(DUMMY_CONFIG, client=FakeAirtable(records or [RESEARCH_RECORD]), exa_client=exa)


def call(tool, args):
    return call_on(make_server(), tool, args)


def call_on(mcp, tool, args):
    async def run():
        async with Client(mcp) as client:
            return await client.call_tool(tool, args)

    return asyncio.run(run())


def tool_names(mcp):
    async def run():
        async with Client(mcp) as client:
            return {t.name for t in await client.list_tools()}

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


def test_research_tools_absent_without_exa():
    names = tool_names(make_server())
    assert "research" not in names
    assert "research_participant" not in names


def test_research_tools_registered_with_exa():
    names = tool_names(make_server_with_exa(FakeExa()))
    assert {"research", "research_participant"} <= names


def test_research_participant_returns_grounded_results():
    grounded = ResearchResult(title="Ada Lovelace", url="https://linkedin.com/in/ada-lovelace", snippet="Founder")
    exa = FakeExa(results=[grounded])  # matches the record's known LinkedIn URL
    data = call_on(make_research_server(exa), "research_participant", {"id": "rec1"}).data
    assert data["participant"] == {"id": "rec1", "name": "Ada Lovelace"}
    assert data["query"].startswith("Ada Lovelace")
    assert data["grounded_on"]["linkedin"] is True
    assert data["count"] == 1
    assert data["results"][0]["url"] == "https://linkedin.com/in/ada-lovelace"
    # Over-fetches (more than num_results) before grounding, using the built query.
    assert len(exa.calls) == 1
    assert exa.calls[0][0] == data["query"]
    assert exa.calls[0][1] >= 5


def test_research_participant_filters_out_ungrounded_results():
    grounded = ResearchResult(title="Ada", url="https://linkedin.com/in/ada-lovelace", snippet="x")
    stranger = ResearchResult(title="Other Ada", url="https://x/other", snippet="an unrelated person in Paris")
    data = call_on(
        make_research_server(FakeExa(results=[grounded, stranger])),
        "research_participant",
        {"id": "rec1"},
    ).data
    urls = [r["url"] for r in data["results"]]
    assert "https://linkedin.com/in/ada-lovelace" in urls
    assert "https://x/other" not in urls


def test_research_participant_unknown_id_errors():
    import pytest

    with pytest.raises(Exception, match="No participant found"):
        call_on(make_server_with_exa(FakeExa()), "research_participant", {"id": "nope"})


def test_research_general_query_passes_through():
    exa = FakeExa()
    data = call_on(make_server_with_exa(exa), "research", {"query": "fintech founders", "num_results": 3}).data
    assert data["query"] == "fintech founders"
    assert data["results"][0]["title"] == "Ada in TechCrunch"
    assert exa.calls == [("fintech founders", 3)]
