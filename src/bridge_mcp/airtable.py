"""A small, schema-agnostic Airtable client with in-memory caching.

It uses the public Airtable REST API:
  * Metadata API   GET /v0/meta/bases/{baseId}/tables   -> discover fields dynamically
  * Records API    GET /v0/{baseId}/{tableIdOrName}      -> list / fetch records

Records are cached in memory for a configurable TTL so that `search`, `fetch`
and `list` stay fast and don't hammer the Airtable API (which is rate limited
to ~5 requests/second per base).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import httpx

API_ROOT = "https://api.airtable.com/v0"
WEB_ROOT = "https://airtable.com"
_PAGE_SIZE = 100


@dataclass
class TableSchema:
    """The shape of the participants table, discovered at runtime."""

    id: str
    name: str
    primary_field_name: str
    fields: list[dict[str, Any]]  # each: {"id", "name", "type", "description"?}

    @property
    def field_names(self) -> list[str]:
        return [f["name"] for f in self.fields]


@dataclass
class _Cache:
    records: list[dict[str, Any]] | None = None
    fetched_at: float = 0.0
    schema: TableSchema | None = None
    by_id: dict[str, dict[str, Any]] = field(default_factory=dict)


class AirtableError(RuntimeError):
    """Raised when the Airtable API returns an error we can't recover from."""


class AirtableClient:
    """Read-only Airtable access scoped to a single base + table."""

    def __init__(
        self,
        api_key: str,
        base_id: str,
        table_name: str | None = None,
        view: str | None = None,
        cache_ttl_seconds: int = 300,
        client: httpx.Client | None = None,
    ) -> None:
        self._base_id = base_id
        self._table_name = table_name
        self._view = view
        self._ttl = cache_ttl_seconds
        self._cache = _Cache()
        self._http = client or httpx.Client(
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30.0,
        )

    # ── HTTP plumbing ─────────────────────────────────────────────────────────
    def _get(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            resp = self._http.get(url, params=params)
        except httpx.HTTPError as exc:  # network-level failure
            raise AirtableError(f"Could not reach Airtable: {exc}") from exc
        if resp.status_code == 401:
            raise AirtableError(
                "Airtable rejected the credentials (401). Check AIRTABLE_API_KEY and "
                "that the token has data.records:read + schema.bases:read scopes."
            )
        if resp.status_code == 404:
            raise AirtableError(
                "Airtable returned 404. Check AIRTABLE_BASE_ID / AIRTABLE_TABLE_NAME "
                "and that the token is granted access to the base."
            )
        if resp.status_code >= 400:
            raise AirtableError(f"Airtable API error {resp.status_code}: {resp.text}")
        return resp.json()

    # ── Schema discovery ────────────────────────────────────────────────────────
    def get_schema(self, *, force: bool = False) -> TableSchema:
        """Discover the participants table's fields via the Airtable Metadata API."""
        if self._cache.schema is not None and not force:
            return self._cache.schema

        data = self._get(f"{API_ROOT}/meta/bases/{self._base_id}/tables")
        tables = data.get("tables", [])
        if not tables:
            raise AirtableError("The base contains no tables.")

        table = self._select_table(tables)
        primary_id = table.get("primaryFieldId")
        fields = table.get("fields", [])
        primary_name = next(
            (f["name"] for f in fields if f.get("id") == primary_id),
            fields[0]["name"] if fields else "Name",
        )
        schema = TableSchema(
            id=table["id"],
            name=table["name"],
            primary_field_name=primary_name,
            fields=[
                {
                    "id": f.get("id"),
                    "name": f.get("name"),
                    "type": f.get("type"),
                    "description": f.get("description"),
                }
                for f in fields
            ],
        )
        self._cache.schema = schema
        return schema

    def _select_table(self, tables: list[dict[str, Any]]) -> dict[str, Any]:
        if not self._table_name:
            return tables[0]
        for t in tables:
            if t.get("name") == self._table_name or t.get("id") == self._table_name:
                return t
        available = ", ".join(t.get("name", "?") for t in tables)
        raise AirtableError(
            f"Table {self._table_name!r} not found in base. Available tables: {available}"
        )

    # ── Records ───────────────────────────────────────────────────────────────
    def _fetch_all_records(self) -> list[dict[str, Any]]:
        """Page through every record in the table (network call)."""
        schema = self.get_schema()
        records: list[dict[str, Any]] = []
        params: dict[str, Any] = {"pageSize": _PAGE_SIZE}
        if self._view:
            params["view"] = self._view

        url = f"{API_ROOT}/{self._base_id}/{schema.id}"
        offset: str | None = None
        while True:
            page_params = dict(params)
            if offset:
                page_params["offset"] = offset
            data = self._get(url, params=page_params)
            records.extend(data.get("records", []))
            offset = data.get("offset")
            if not offset:
                break
        return records

    def get_records(self, *, force: bool = False) -> list[dict[str, Any]]:
        """Return all records, served from cache when fresh."""
        fresh = (
            self._cache.records is not None
            and (time.monotonic() - self._cache.fetched_at) < self._ttl
        )
        if fresh and not force:
            return self._cache.records  # type: ignore[return-value]

        records = self._fetch_all_records()
        self._cache.records = records
        self._cache.fetched_at = time.monotonic()
        self._cache.by_id = {r["id"]: r for r in records}
        return records

    def get_record(self, record_id: str) -> dict[str, Any] | None:
        """Return a single record by Airtable record id (uses cache, falls back to API)."""
        # Refresh cache index if needed.
        self.get_records()
        if record_id in self._cache.by_id:
            return self._cache.by_id[record_id]

        # Not in cache (e.g. added since last fetch) — fetch directly.
        schema = self.get_schema()
        url = f"{API_ROOT}/{self._base_id}/{schema.id}/{record_id}"
        try:
            record = self._get(url)
        except AirtableError:
            return None
        if record and "id" in record:
            self._cache.by_id[record["id"]] = record
            return record
        return None

    def record_url(self, record_id: str) -> str:
        """A deep link to the record in the Airtable UI (used for citations)."""
        schema = self.get_schema()
        return f"{WEB_ROOT}/{self._base_id}/{schema.id}/{record_id}"
