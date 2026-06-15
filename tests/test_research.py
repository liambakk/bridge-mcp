import json

import httpx
import pytest

from bridge_mcp.research import ExaClient, ExaError, participant_query

EXA_RESPONSE = {
    "requestId": "r1",
    "results": [
        {
            "title": "Ada at Engines",
            "url": "https://ex.com/ada",
            "publishedDate": "2024-01-02",
            "author": "Reporter",
            "text": "Ada founded Engines, a deep tech startup building analytical machines.",
        },
        {"title": "Profile", "url": "https://ex.com/p", "author": None, "text": "More about Ada."},
    ],
}


def make_client(handler, **kwargs) -> ExaClient:
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport, headers={"x-api-key": "x"})
    return ExaClient(api_key="x", client=http, **kwargs)


def test_search_posts_query_and_parses_results():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        captured["key"] = request.headers.get("x-api-key")
        return httpx.Response(200, json=EXA_RESPONSE)

    results = make_client(handler).search("Ada Lovelace Engines")

    assert captured["url"] == "https://api.exa.ai/search"
    assert captured["body"]["query"] == "Ada Lovelace Engines"
    assert captured["body"]["contents"]["text"]["maxCharacters"] > 0
    assert captured["key"] == "x"
    assert results[0].title == "Ada at Engines"
    assert results[0].url == "https://ex.com/ada"
    assert results[0].author == "Reporter"
    assert "Engines" in results[0].snippet
    assert results[1].author is None


def test_empty_query_skips_the_network():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("Exa should not be called for an empty query")

    assert make_client(handler).search("   ") == []


def test_num_results_is_capped():
    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["numResults"] == 25
        return httpx.Response(200, json={"results": []})

    make_client(handler).search("anything", num_results=999)


def test_401_is_friendly():
    client = make_client(lambda r: httpx.Response(401, text="nope"))
    with pytest.raises(ExaError, match="401"):
        client.search("x")


def test_malformed_results_are_skipped():
    payload = {"results": [{"no_url": 1}, "garbage", {"url": "https://ok.com", "title": "Ok"}]}
    client = make_client(lambda r: httpx.Response(200, json=payload))
    results = client.search("x")
    assert [r.url for r in results] == ["https://ok.com"]


def test_participant_query_combines_name_and_company():
    record = {"id": "rec1", "fields": {"Name": "Ada Lovelace", "Company": "Engines"}}
    assert participant_query(record, "Name") == "Ada Lovelace Engines"


def test_participant_query_falls_back_to_name_only():
    record = {"id": "rec1", "fields": {"Name": "Ada Lovelace"}}
    assert participant_query(record, "Name") == "Ada Lovelace"


def test_participant_query_uses_one_liner_when_no_company():
    record = {"id": "rec1", "fields": {"full_name": "Aimar Haddadi", "one_liner": "building AI-native spaces"}}
    assert participant_query(record, "full_name") == "Aimar Haddadi building AI-native spaces"


def test_participant_query_ignores_generic_role_field():
    # `role` is identical across the cohort ("CEO or CTO"), so it must not be
    # appended — a name-only query disambiguates better than a shared role string.
    record = {"id": "rec1", "fields": {"full_name": "Aimar Haddadi", "role": "CEO or CTO"}}
    assert participant_query(record, "full_name") == "Aimar Haddadi"


def test_participant_query_caps_context_length_without_ellipsis():
    long_one_liner = "building " + "ai " * 60  # well over the cap
    record = {"id": "rec1", "fields": {"full_name": "Aimar Haddadi", "one_liner": long_one_liner}}
    query = participant_query(record, "full_name")
    appended = query[len("Aimar Haddadi "):]
    assert len(appended) <= 80
    assert "…" not in query
    assert query.startswith("Aimar Haddadi building ai")
