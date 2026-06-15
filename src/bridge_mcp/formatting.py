"""Helpers for turning raw Airtable records into search results and readable text.

These are deliberately schema-agnostic: they work with whatever fields the
participants table happens to have, so the server keeps working if columns
are added, removed or renamed.
"""

from __future__ import annotations

import re
from typing import Any


def stringify_value(value: Any) -> str:
    """Render any Airtable field value as a human-readable string."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (int, float, str)):
        return str(value)
    if isinstance(value, list):
        return ", ".join(stringify_value(v) for v in value if v is not None)
    if isinstance(value, dict):
        # Attachments, collaborators, thumbnails, etc. Prefer a friendly key.
        for key in ("name", "email", "url", "text", "label", "value"):
            if key in value and value[key]:
                return stringify_value(value[key])
        return ", ".join(
            f"{k}: {stringify_value(v)}" for k, v in value.items() if v is not None
        )
    return str(value)


def record_title(record: dict[str, Any], primary_field: str) -> str:
    """Best-effort display name for a record."""
    fields = record.get("fields", {})
    title = stringify_value(fields.get(primary_field)).strip()
    if title:
        return title
    # Fall back to common name-ish fields, then the record id.
    for candidate in ("Name", "Full Name", "Founder", "Participant", "Title"):
        val = stringify_value(fields.get(candidate)).strip()
        if val:
            return val
    return record.get("id", "Untitled")


def record_to_text(record: dict[str, Any], field_order: list[str] | None = None) -> str:
    """Render a record's fields as a readable 'Field: value' block."""
    fields = record.get("fields", {})
    keys = field_order or list(fields.keys())
    # Include any fields present on the record but missing from field_order.
    keys = keys + [k for k in fields.keys() if k not in keys]

    lines: list[str] = []
    for key in keys:
        if key not in fields:
            continue
        rendered = stringify_value(fields[key]).strip()
        if rendered:
            lines.append(f"{key}: {rendered}")
    return "\n".join(lines) if lines else "(no fields)"


def _searchable_blob(record: dict[str, Any]) -> str:
    fields = record.get("fields", {})
    return " ".join(stringify_value(v) for v in fields.values()).lower()


def _snippet(text: str, limit: int = 200) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def search_records(
    records: list[dict[str, Any]],
    query: str,
    primary_field: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Rank records against a free-text query.

    Scoring is simple and predictable: each whitespace-separated term in the
    query that appears anywhere in the record scores a point, with a small bonus
    for matches in the title. An empty query returns the first `limit` records.
    """
    terms = [t for t in re.split(r"\s+", query.lower().strip()) if t]

    scored: list[tuple[float, dict[str, Any]]] = []
    for record in records:
        blob = _searchable_blob(record)
        title = record_title(record, primary_field).lower()

        if not terms:
            score = 1.0
        else:
            score = 0.0
            for term in terms:
                if term in title:
                    score += 2.0
                elif term in blob:
                    score += 1.0
            if score == 0.0:
                continue
        scored.append((score, record))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [record for _score, record in scored[:limit]]


def search_result(record: dict[str, Any], primary_field: str, url: str) -> dict[str, Any]:
    """Shape one record into a ChatGPT-compatible search result."""
    return {
        "id": record["id"],
        "title": record_title(record, primary_field),
        "url": url,
        "text": _snippet(record_to_text(record)),
    }
