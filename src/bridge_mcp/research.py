"""A tiny Exa client for enriching participants with public web research.

Backs the optional `research` / `research_participant` MCP tools. Given a
free-text query (typically a participant's name + company), it queries Exa's
REST search API (POST https://api.exa.ai/search) and returns ranked web results
with short text excerpts and source URLs the model can cite.

Exa responses are treated as untrusted third-party data: every field is
shape-checked and coerced before it leaves this module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import httpx

from .formatting import record_title, stringify_value

API_URL = "https://api.exa.ai/search"
_DEFAULT_NUM_RESULTS = 5
_MAX_NUM_RESULTS = 25  # cap to bound cost / latency, whatever a caller asks for
_MAX_CHARACTERS = 1000  # how much page text Exa returns per result
# Short, identifying fields we fold into a participant's research query when
# present — generic Airtable column names first, then common export field names
# (role / one-liner). The first non-empty match wins, capped to a few words so a
# long free-text value doesn't bloat or over-narrow the search.
# Short, identifying fields we fold into a participant's research query when
# present: an actual org name first, then a descriptive one-liner / headline.
# We deliberately exclude generic role/title fields (e.g. "CEO or CTO") — they're
# the same across people, so they add noise and match unrelated profiles rather
# than disambiguate. When none of these are present, the bare name is the query.
_CONTEXT_FIELDS = (
    "Company", "Startup", "Organisation", "Organization", "Business", "Venture",
    "one_liner", "headline", "tagline",
)
_MAX_CONTEXT_CHARS = 80


class ExaError(RuntimeError):
    """Raised when the Exa API returns an error we can't recover from."""


@dataclass
class ResearchResult:
    """One web source, normalised down to what a client needs to cite it."""

    title: str
    url: str
    snippet: str
    published_date: str | None = None
    author: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "published_date": self.published_date,
            "author": self.author,
        }


def participant_query(record: dict[str, Any], primary_field: str) -> str:
    """Build a web-research query for a participant: their name plus a short
    identifying detail (company / role / one-liner) when the data has one."""
    name = record_title(record, primary_field)
    fields = record.get("fields", {})
    for candidate in _CONTEXT_FIELDS:
        context = re.sub(r"\s+", " ", stringify_value(fields.get(candidate))).strip()
        if not context or context.lower() in name.lower():
            continue
        if len(context) > _MAX_CONTEXT_CHARS:
            context = context[:_MAX_CONTEXT_CHARS].rsplit(" ", 1)[0].rstrip()
        return f"{name} {context}".strip()
    return name


def _clean(value: Any, limit: int = 600) -> str:
    """Collapse whitespace and truncate any Exa value to a safe, bounded string."""
    text = re.sub(r"\s+", " ", stringify_value(value)).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


class ExaClient:
    """Read-only Exa web search, scoped to short cited excerpts."""

    source = "exa"

    def __init__(
        self,
        api_key: str,
        *,
        num_results: int = _DEFAULT_NUM_RESULTS,
        max_characters: int = _MAX_CHARACTERS,
        client: httpx.Client | None = None,
        timeout: float = 20.0,
    ) -> None:
        self._num_results = num_results
        self._max_characters = max_characters
        self._http = client or httpx.Client(
            headers={"x-api-key": api_key, "Content-Type": "application/json"},
            timeout=timeout,
        )

    def search(self, query: str, *, num_results: int | None = None) -> list[ResearchResult]:
        """Search the public web for `query` and return bounded, cited results."""
        query = (query or "").strip()
        if not query:
            return []
        n = max(1, min(num_results or self._num_results, _MAX_NUM_RESULTS))
        payload = {
            "query": query,
            "numResults": n,
            "type": "auto",
            "contents": {"text": {"maxCharacters": self._max_characters}},
        }
        try:
            resp = self._http.post(API_URL, json=payload)
        except httpx.HTTPError as exc:  # network-level failure
            raise ExaError(f"Could not reach Exa: {exc}") from exc
        if resp.status_code == 401:
            raise ExaError("Exa rejected the credentials (401). Check EXA_API_KEY.")
        if resp.status_code == 429:
            raise ExaError("Exa rate limit hit (429). Try again shortly.")
        if resp.status_code >= 400:
            raise ExaError(f"Exa API error {resp.status_code}: {resp.text[:200]}")
        try:
            data = resp.json()
        except ValueError as exc:
            raise ExaError(f"Exa returned invalid JSON: {exc}") from exc

        results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(results, list):
            return []
        parsed = (self._parse(r) for r in results if isinstance(r, dict))
        return [r for r in parsed if r is not None][:n]

    @staticmethod
    def _parse(raw: dict[str, Any]) -> ResearchResult | None:
        url = stringify_value(raw.get("url")).strip()
        if not url:
            return None
        return ResearchResult(
            title=_clean(raw.get("title"), 200) or url,
            url=url,
            snippet=_clean(raw.get("text") or raw.get("summary")),
            published_date=_clean(raw.get("publishedDate"), 40) or None,
            author=_clean(raw.get("author"), 120) or None,
        )
