import json

import httpx
import pytest

from bridge_mcp.airtable import AirtableClient, AirtableError

BASE_ID = "appTEST"

SCHEMA_RESPONSE = {
    "tables": [
        {
            "id": "tblParticipants",
            "name": "Participants",
            "primaryFieldId": "fldName",
            "fields": [
                {"id": "fldName", "name": "Name", "type": "singleLineText"},
                {"id": "fldCo", "name": "Company", "type": "singleLineText"},
            ],
        },
        {
            "id": "tblOther",
            "name": "Other",
            "primaryFieldId": "fldX",
            "fields": [{"id": "fldX", "name": "X", "type": "singleLineText"}],
        },
    ]
}


def make_client(handler, **kwargs) -> AirtableClient:
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport, headers={"Authorization": "Bearer x"})
    return AirtableClient(
        api_key="x", base_id=BASE_ID, client=http, cache_ttl_seconds=300, **kwargs
    )


def test_schema_selects_named_table_and_primary_field():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/v0/meta/bases/{BASE_ID}/tables"
        return httpx.Response(200, json=SCHEMA_RESPONSE)

    client = make_client(handler, table_name="Participants")
    schema = client.get_schema()
    assert schema.id == "tblParticipants"
    assert schema.primary_field_name == "Name"
    assert schema.field_names == ["Name", "Company"]


def test_schema_defaults_to_first_table():
    client = make_client(lambda r: httpx.Response(200, json=SCHEMA_RESPONSE))
    assert client.get_schema().id == "tblParticipants"


def test_unknown_table_name_raises():
    client = make_client(
        lambda r: httpx.Response(200, json=SCHEMA_RESPONSE), table_name="Nope"
    )
    with pytest.raises(AirtableError, match="not found"):
        client.get_schema()


def test_records_are_paginated_and_cached():
    calls = {"records": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if "meta/bases" in request.url.path:
            return httpx.Response(200, json=SCHEMA_RESPONSE)
        calls["records"] += 1
        if "offset" not in request.url.params:
            return httpx.Response(
                200,
                json={"records": [{"id": "rec1", "fields": {"Name": "A"}}], "offset": "pg2"},
            )
        return httpx.Response(200, json={"records": [{"id": "rec2", "fields": {"Name": "B"}}]})

    client = make_client(handler, table_name="Participants")
    records = client.get_records()
    assert [r["id"] for r in records] == ["rec1", "rec2"]
    assert calls["records"] == 2  # two pages

    # Second call is served from cache (no extra record requests).
    client.get_records()
    assert calls["records"] == 2


def test_get_record_uses_cache_then_falls_back_to_api():
    def handler(request: httpx.Request) -> httpx.Response:
        if "meta/bases" in request.url.path:
            return httpx.Response(200, json=SCHEMA_RESPONSE)
        if request.url.path.endswith("/recDIRECT"):
            return httpx.Response(200, json={"id": "recDIRECT", "fields": {"Name": "Direct"}})
        return httpx.Response(200, json={"records": [{"id": "rec1", "fields": {"Name": "A"}}]})

    client = make_client(handler, table_name="Participants")
    assert client.get_record("rec1")["fields"]["Name"] == "A"
    assert client.get_record("recDIRECT")["fields"]["Name"] == "Direct"
    assert client.get_record("missing") is None


def test_auth_failure_is_friendly():
    client = make_client(lambda r: httpx.Response(401, text="nope"))
    with pytest.raises(AirtableError, match="401"):
        client.get_schema()


def test_record_url_is_deep_link():
    client = make_client(
        lambda r: httpx.Response(200, json=SCHEMA_RESPONSE), table_name="Participants"
    )
    url = client.record_url("rec1")
    assert url == f"https://airtable.com/{BASE_ID}/tblParticipants/rec1"
