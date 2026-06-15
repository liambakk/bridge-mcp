"""Runtime configuration, loaded from environment variables (and an optional .env)."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    """Everything the server needs to talk to Airtable and serve clients."""

    api_key: str
    base_id: str
    table_name: str | None
    view: str | None
    cache_ttl_seconds: int
    auth_token: str | None
    host: str
    port: int
    data_file: str | None = None
    # WorkOS AuthKit OAuth (required for claude.ai web / ChatGPT remote connectors).
    # When both are set, the server authenticates via OAuth instead of a bearer token.
    authkit_domain: str | None = None
    public_url: str | None = None
    # Exa web search. When set, the server exposes optional `research` /
    # `research_participant` tools that enrich profiles with public web sources.
    exa_api_key: str | None = None


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Missing required environment variable {name!r}. "
            "Copy .env.example to .env and fill it in, or export it before starting."
        )
    return value


def load_config() -> Config:
    """Load configuration from the environment, reading a local .env file if present."""
    load_dotenv()

    def _opt(name: str) -> str | None:
        value = os.environ.get(name, "").strip()
        return value or None

    # When a local JSON export is provided, Airtable credentials are optional —
    # the server reads from disk instead of the live API.
    data_file = _opt("BRIDGE_DATA_FILE")
    if data_file:
        api_key = _opt("AIRTABLE_API_KEY") or ""
        base_id = _opt("AIRTABLE_BASE_ID") or ""
    else:
        api_key = _require("AIRTABLE_API_KEY")
        base_id = _require("AIRTABLE_BASE_ID")

    return Config(
        api_key=api_key,
        base_id=base_id,
        table_name=_opt("AIRTABLE_TABLE_NAME"),
        view=_opt("AIRTABLE_VIEW"),
        cache_ttl_seconds=int(os.environ.get("CACHE_TTL_SECONDS", "300")),
        auth_token=_opt("BRIDGE_MCP_TOKEN"),
        host=os.environ.get("HOST", "0.0.0.0").strip() or "0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
        data_file=data_file,
        authkit_domain=_opt("AUTHKIT_DOMAIN"),
        public_url=_opt("BRIDGE_PUBLIC_URL"),
        exa_api_key=_opt("EXA_API_KEY"),
    )
