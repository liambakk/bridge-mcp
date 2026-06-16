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

# ── Grounding ────────────────────────────────────────────────────────────────
# A participant search is anchored to identifiers we already hold in the record:
# their LinkedIn URL and the web / email domains in their profile (a personal
# site, a company domain, a university address). Those are unique to the person,
# so the query is built from them and every Exa result is kept only if it
# corroborates one — the search can't drift to a same-name stranger. (Earlier
# attempts to mine company/school names out of prose proved too noisy on real
# bios; domains are the reliable signal.)
_MAX_ANCHORS = 12
_MIN_LABEL_LEN = 3

# Domains that identify a platform, not a person: free-mail, social, shorteners.
_GENERIC_DOMAINS = {
    "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "yahoo.com",
    "icloud.com", "me.com", "mac.com", "proton.me", "protonmail.com", "aol.com",
    "live.com", "msn.com", "gmx.com", "yandex.com", "qq.com",
    "linkedin.com", "lnkd.in", "twitter.com", "x.com", "github.com", "github.io",
    "instagram.com", "facebook.com", "fb.com", "threads.com", "threads.net",
    "youtube.com", "youtu.be", "medium.com", "substack.com", "tiktok.com",
    "t.co", "bit.ly", "notion.so", "notion.site", "calendly.com", "gravatar.com",
}
# Domain labels too generic to anchor on even when they're someone's own domain.
_GENERIC_LABELS = {"data", "tech", "app", "dev", "get", "the", "my", "co", "hq", "io", "ai"}
_ALLOWED_TLDS = {
    "com", "org", "net", "io", "ai", "co", "dev", "app", "xyz", "me", "tech",
    "so", "gg", "page", "site", "uk", "de", "fr", "es", "nl", "eu", "us", "ca",
    "au", "ch", "se", "no", "fi", "it", "ie", "ac", "edu",
}

_LINKEDIN_RE = re.compile(r"https?://[^\s,'\")]*linkedin\.com/[^\s,'\")]+", re.I)
_DOMAIN_RE = re.compile(r"\b([a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)+)\b", re.I)


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


def _normalize_url(url: Any) -> str:
    """Strip scheme / www / query / trailing slash so URLs compare equal."""
    u = stringify_value(url).strip().lower()
    u = re.sub(r"^https?://", "", u)
    u = re.sub(r"^www\.", "", u)
    return u.split("?")[0].split("#")[0].rstrip("/")


def _mineable(value: Any) -> bool:
    """True for free-text fields. Skips attachments (lists of dicts) and the like,
    whose filenames/URLs would otherwise be mistaken for the person's own domain."""
    if isinstance(value, str):
        return True
    if isinstance(value, list):
        return all(isinstance(x, str) for x in value)
    return False


def _known_domains(text: str) -> list[str]:
    """Extract identifying web / email domains from a record's free text."""
    domains: list[str] = []
    seen: set[str] = set()
    for raw in _DOMAIN_RE.findall(text):
        domain = raw.lower().strip(".")
        if domain.startswith("www."):
            domain = domain[4:]  # so www.linkedin.com collapses to the excluded linkedin.com
        if domain in seen or domain in _GENERIC_DOMAINS:
            continue
        if domain.rsplit(".", 1)[-1] not in _ALLOWED_TLDS:
            continue
        seen.add(domain)
        domains.append(domain)
    return domains


@dataclass
class Grounding:
    """A participant search anchored to identifiers from their own record."""

    name: str
    query: str
    linkedin_url: str | None      # normalized
    domains: tuple[str, ...]      # identifying web / email domains, e.g. "nusmark.com"
    labels: tuple[str, ...]       # their registrable names, e.g. "nusmark"

    @property
    def has_anchors(self) -> bool:
        return bool(self.linkedin_url or self.domains)

    def anchors_used(self) -> dict[str, Any]:
        return {"linkedin": bool(self.linkedin_url), "domains": list(self.domains)}

    def is_grounded(self, result: "ResearchResult") -> bool:
        """True if `result` corroborates an identifier we hold for this person."""
        url = _normalize_url(result.url)
        if self.linkedin_url and url == self.linkedin_url:
            return True
        hay = f"{result.title} {result.snippet} {url}".lower()
        if any(domain in hay for domain in self.domains):
            return True
        if any(re.search(rf"\b{re.escape(label)}\b", hay) for label in self.labels):
            return True
        # No identifiers at all (name only) — fall back to requiring the full name.
        if not self.has_anchors:
            return all(tok in hay for tok in self.name.lower().split())
        return False


def build_grounding(record: dict[str, Any], primary_field: str) -> Grounding:
    """Build a record-grounded query + verifier from a participant's own data."""
    name = record_title(record, primary_field)
    fields = record.get("fields", {})
    full_text = " ".join(stringify_value(v) for v in fields.values())

    m = _LINKEDIN_RE.search(full_text)
    linkedin_url = _normalize_url(m.group(0)) if m else None

    # Identifying domains come only from real text fields (not attachments).
    text = " ".join(stringify_value(v) for k, v in fields.items() if _mineable(v))
    domains = _known_domains(text)[:_MAX_ANCHORS]
    labels: list[str] = []
    for domain in domains:
        label = domain.split(".")[0]
        if len(label) >= _MIN_LABEL_LEN and label not in _GENERIC_LABELS and label not in labels:
            labels.append(label)

    # The query is the name plus a couple of distinctive domain labels, which bias
    # Exa toward the right person (e.g. "Emre Karaoglu tensor-omega").
    query = re.sub(r"\s+", " ", f"{name} {' '.join(labels[:2])}").strip()

    return Grounding(
        name=name,
        query=query,
        linkedin_url=linkedin_url,
        domains=tuple(domains),
        labels=tuple(labels),
    )


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
