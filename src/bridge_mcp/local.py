"""A file-backed, read-only data source that mirrors :class:`AirtableClient`.

Used when live Airtable access isn't available: point ``BRIDGE_DATA_FILE`` at a
JSON export of the table and the server serves identical `search` / `fetch` /
`list_participants` / `describe_table` tools from disk — no network required.

The export is expected in Airtable's own shape::

    {"records": [{"id": "rec...", "createdTime": "...", "fields": {...}}, ...]}

A bare top-level list of those record objects is also accepted. The table schema
(field names + best-effort types, primary field) is inferred from the records,
keeping the server schema-agnostic.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .airtable import WEB_ROOT, AirtableError, TableSchema


def _infer_type(values: list[Any]) -> str:
    """Best-effort Airtable-ish field type from the values seen across records."""
    for value in values:
        if value in (None, "", [], {}):
            continue
        if isinstance(value, bool):
            return "checkbox"
        if isinstance(value, (int, float)):
            return "number"
        if isinstance(value, list):
            head = value[0] if value else None
            if isinstance(head, dict) and ("url" in head or "filename" in head):
                return "multipleAttachments"
            return "multipleSelects"
        if isinstance(value, str):
            return "multilineText" if ("\n" in value or len(value) > 80) else "singleLineText"
        return "singleLineText"
    return "singleLineText"


class LocalClient:
    """Read-only access to a JSON export, duck-typed to :class:`AirtableClient`."""

    source = "local-file"

    def __init__(
        self,
        path: str,
        base_id: str | None = None,
        table_name: str | None = None,
    ) -> None:
        self._path = Path(path)
        self._base_id = base_id
        self._table_name = table_name
        self._records = self._load()
        self._by_id = {r["id"]: r for r in self._records}
        self._schema = self._build_schema()

    # ── Loading ───────────────────────────────────────────────────────────────
    def _load(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            raise AirtableError(f"Data file not found: {self._path}")
        try:
            raw = json.loads(self._path.read_text())
        except json.JSONDecodeError as exc:
            raise AirtableError(f"Data file {self._path} is not valid JSON: {exc}") from exc

        records = raw.get("records") if isinstance(raw, dict) else raw
        if not isinstance(records, list):
            raise AirtableError(
                f"Data file {self._path} must be a list of records or "
                '{"records": [...]}.'
            )
        normalised: list[dict[str, Any]] = []
        for i, rec in enumerate(records):
            if not isinstance(rec, dict) or "fields" not in rec:
                raise AirtableError(
                    f"Record {i} in {self._path} is missing a 'fields' object."
                )
            normalised.append({"id": rec.get("id") or f"rec{i:06d}", "fields": rec["fields"]})
        return normalised

    def _build_schema(self) -> TableSchema:
        order: list[str] = []
        seen: set[str] = set()
        for rec in self._records:
            for key in rec["fields"]:
                if key not in seen:
                    seen.add(key)
                    order.append(key)
        fields = [
            {
                "id": None,
                "name": name,
                "type": _infer_type([r["fields"].get(name) for r in self._records]),
                "description": None,
            }
            for name in order
        ]
        return TableSchema(
            id=self._table_name or self._path.stem,
            name=self._table_name or self._path.stem,
            primary_field_name=order[0] if order else "Name",
            fields=fields,
        )

    # ── AirtableClient-compatible interface ───────────────────────────────────
    def get_schema(self, *, force: bool = False) -> TableSchema:
        return self._schema

    def get_records(self, *, force: bool = False) -> list[dict[str, Any]]:
        return self._records

    def get_record(self, record_id: str) -> dict[str, Any] | None:
        return self._by_id.get(record_id)

    def record_url(self, record_id: str) -> str:
        if self._base_id:
            return f"{WEB_ROOT}/{self._base_id}/{record_id}"
        return f"urn:bridge:participant:{record_id}"
