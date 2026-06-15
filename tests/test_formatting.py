from bridge_mcp.formatting import (
    record_title,
    record_to_text,
    search_records,
    search_result,
    stringify_value,
)

RECORDS = [
    {
        "id": "rec001",
        "fields": {
            "Name": "Ada Lovelace",
            "Company": "Analytical Engines",
            "Sector": "Deep Tech",
            "Wants to meet": ["ML engineers", "hardware founders"],
            "Confirmed": True,
        },
    },
    {
        "id": "rec002",
        "fields": {
            "Name": "Grace Hopper",
            "Company": "Compiler Co",
            "Sector": "Developer Tools",
            "Wants to meet": ["fintech founders"],
        },
    },
]


def test_stringify_handles_scalars_lists_and_dicts():
    assert stringify_value("hi") == "hi"
    assert stringify_value(True) == "Yes"
    assert stringify_value([1, 2, 3]) == "1, 2, 3"
    assert stringify_value({"name": "Acme", "id": "x"}) == "Acme"
    assert stringify_value(None) == ""


def test_record_title_prefers_primary_field():
    assert record_title(RECORDS[0], "Name") == "Ada Lovelace"


def test_record_title_falls_back_to_id():
    assert record_title({"id": "recX", "fields": {}}, "Name") == "recX"


def test_record_to_text_renders_field_lines():
    text = record_to_text(RECORDS[0], ["Name", "Company", "Sector"])
    assert "Name: Ada Lovelace" in text
    assert "Company: Analytical Engines" in text
    assert "Confirmed: Yes" in text  # field outside the order is still included


def test_search_ranks_title_matches_first():
    results = search_records(RECORDS, "Grace", "Name", limit=10)
    assert results[0]["id"] == "rec002"


def test_search_matches_non_title_fields():
    results = search_records(RECORDS, "fintech", "Name", limit=10)
    assert [r["id"] for r in results] == ["rec002"]


def test_empty_query_returns_sample():
    results = search_records(RECORDS, "", "Name", limit=1)
    assert len(results) == 1


def test_search_result_shape_is_chatgpt_compatible():
    result = search_result(RECORDS[0], "Name", "https://airtable.com/app/tbl/rec001")
    assert set(result) == {"id", "title", "url", "text"}
    assert result["id"] == "rec001"
    assert result["title"] == "Ada Lovelace"
