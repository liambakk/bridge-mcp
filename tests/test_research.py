import json

import httpx
import pytest

from bridge_mcp.research import ExaClient, ExaError, ResearchResult, build_grounding

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


# ── Grounding ────────────────────────────────────────────────────────────────

PAUL = {
    "id": "rec1",
    "fields": {
        "full_name": "Paul Gailey",
        "email": "paul@kcl.ac.uk",
        "linkedin": "https://www.linkedin.com/in/paul-gailey/",
        "most_impressive_build": "As an FDE at Palantir I owned delivery; Data Science at KCL.",
    },
}


EMRE = {
    "id": "rec2",
    "fields": {
        "full_name": "Emre Karaoglu",
        "linkedin": "https://www.linkedin.com/in/emre-karaoglu/",
        "most_impressive_build": "TENSOR (tensor-omega.com), a multi-agent research platform.",
    },
}


def test_grounding_extracts_linkedin_url_and_email_domain():
    g = build_grounding(PAUL, "full_name")
    assert g.linkedin_url == "linkedin.com/in/paul-gailey"
    assert "kcl.ac.uk" in g.domains
    assert "kcl" in g.labels


def test_grounding_extracts_website_domain_from_bio():
    g = build_grounding(EMRE, "full_name")
    assert "tensor-omega.com" in g.domains
    assert "tensor-omega" in g.labels


def test_grounding_query_is_name_plus_domain_label():
    g = build_grounding(EMRE, "full_name")
    assert g.query.startswith("Emre Karaoglu")
    assert "tensor-omega" in g.query


def test_grounding_skips_social_and_freemail_domains():
    record = {
        "id": "r",
        "fields": {
            "full_name": "Jo X",
            "email": "jo@gmail.com",
            "linkedin": "https://linkedin.com/in/jo-x",
            "site": "twitter.com/jox",
        },
    }
    g = build_grounding(record, "full_name")
    assert g.domains == ()  # gmail + linkedin + twitter all excluded
    assert g.linkedin_url == "linkedin.com/in/jo-x"


def test_is_grounded_accepts_matching_linkedin_url():
    g = build_grounding(PAUL, "full_name")
    r = ResearchResult(title="Paul Gailey", url="https://linkedin.com/in/paul-gailey", snippet="x")
    assert g.is_grounded(r)


def test_is_grounded_accepts_known_domain_or_label_in_text():
    g = build_grounding(EMRE, "full_name")
    by_url = ResearchResult(title="TENSOR", url="https://tensor-omega.com/", snippet="AI debate platform")
    by_label = ResearchResult(title="Profile", url="https://news.com/x", snippet="creator of tensor-omega")
    assert g.is_grounded(by_url)
    assert g.is_grounded(by_label)


def test_is_grounded_rejects_same_name_stranger():
    g = build_grounding(PAUL, "full_name")
    namesake = ResearchResult(
        title="Paul Gailey Alburquerque",
        url="https://paulgailey.com/",
        snippet="digital marketing director, web admin, smartglass biz dev in Murcia",
    )
    assert not g.is_grounded(namesake)


def test_is_grounded_falls_back_to_full_name_when_no_anchors():
    g = build_grounding({"id": "r", "fields": {"full_name": "Ada Lovelace"}}, "full_name")
    assert not g.has_anchors
    assert g.is_grounded(ResearchResult(title="Ada Lovelace", url="https://x.com", snippet="mathematician"))
    assert not g.is_grounded(ResearchResult(title="Someone Else", url="https://y.com", snippet="unrelated"))
