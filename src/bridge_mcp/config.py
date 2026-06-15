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

    return Config(
        api_key=_require("AIRTABLE_API_KEY"),
        base_id=_require("AIRTABLE_BASE_ID"),
        table_name=_opt("AIRTABLE_TABLE_NAME"),
        view=_opt("AIRTABLE_VIEW"),
        cache_ttl_seconds=int(os.environ.get("CACHE_TTL_SECONDS", "300")),
        auth_token=_opt("BRIDGE_MCP_TOKEN"),
        host=os.environ.get("HOST", "0.0.0.0").strip() or "0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
    )
