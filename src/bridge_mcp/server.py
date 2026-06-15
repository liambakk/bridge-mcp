"""The Bridge participants MCP server.

Exposes Entrepreneur First "The Bridge" attendee data (stored in Airtable) to
any MCP client. It implements the `search` + `fetch` tools that ChatGPT's
connectors / deep research require, plus a couple of richer tools that Claude
and other clients can use directly.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from fastmcp import FastMCP

from .airtable import AirtableClient, AirtableError
from .config import Config, load_config
from .formatting import (
    record_title,
    record_to_text,
    search_records,
    search_result,
)

INSTRUCTIONS = """\
This server provides access to the participants attending Entrepreneur First's
"The Bridge" selection days. Use `search` to find attendees by name, company,
sector, background or who they want to meet, and `fetch` to pull a full profile
by id. `list_participants` returns everyone, and `describe_table` explains which
fields are available. All data is read-only.
"""


def build_server(config: Config, client: AirtableClient | None = None) -> FastMCP:
    """Construct the FastMCP server and register tools.

    `client` can be injected for testing; otherwise one is built from `config`.
    """
    airtable = client or AirtableClient(
        api_key=config.api_key,
        base_id=config.base_id,
        table_name=config.table_name,
        view=config.view,
        cache_ttl_seconds=config.cache_ttl_seconds,
    )

    mcp = FastMCP(name="The Bridge — Participants", instructions=INSTRUCTIONS)

    @mcp.tool
    def search(query: str) -> dict[str, Any]:
        """Search The Bridge participants by free text.

        Matches across every field (name, company, sector, background, who they
        want to meet, etc.). Returns a list of results with an id, title and a
        short snippet. Pass each id to `fetch` to read the full profile.

        Args:
            query: What to look for, e.g. "fintech founder", "wants to meet ML
                engineers", or a person's name. An empty query returns a sample.
        """
        schema = airtable.get_schema()
        records = airtable.get_records()
        matches = search_records(records, query, schema.primary_field_name, limit=20)
        results = [
            search_result(r, schema.primary_field_name, airtable.record_url(r["id"]))
            for r in matches
        ]
        return {"results": results}

    @mcp.tool
    def fetch(id: str) -> dict[str, Any]:
        """Fetch one participant's full profile by id.

        Args:
            id: The participant id returned by `search` (an Airtable record id,
                e.g. "rec0123456789ABCD").
        """
        record = airtable.get_record(id)
        if record is None:
            raise ValueError(f"No participant found with id {id!r}.")
        schema = airtable.get_schema()
        return {
            "id": record["id"],
            "title": record_title(record, schema.primary_field_name),
            "text": record_to_text(record, schema.field_names),
            "url": airtable.record_url(record["id"]),
            "metadata": {"source": "airtable", "table": schema.name},
        }

    @mcp.tool
    def list_participants(limit: int = 200) -> dict[str, Any]:
        """List participants attending The Bridge.

        Returns each participant's id, name and a deep link. Use `fetch` for the
        full profile of anyone interesting.

        Args:
            limit: Maximum number of participants to return (default 200).
        """
        schema = airtable.get_schema()
        records = airtable.get_records()
        participants = [
            {
                "id": r["id"],
                "name": record_title(r, schema.primary_field_name),
                "url": airtable.record_url(r["id"]),
            }
            for r in records[: max(limit, 0)]
        ]
        return {"count": len(participants), "total": len(records), "participants": participants}

    @mcp.tool
    def describe_table() -> dict[str, Any]:
        """Describe the participants table: its name and the available fields.

        Useful for understanding what you can search or filter on before asking
        more specific questions.
        """
        schema = airtable.get_schema()
        return {
            "table": schema.name,
            "primary_field": schema.primary_field_name,
            "fields": [
                {"name": f["name"], "type": f["type"], "description": f.get("description")}
                for f in schema.fields
            ],
        }

    return mcp


# ── Optional bearer-token auth for HTTP hosting ───────────────────────────────
def _add_auth(app: Any, token: str) -> None:
    """Attach a minimal bearer-token check to the Starlette/ASGI app."""
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse

    class BearerAuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):  # type: ignore[override]
            header = request.headers.get("authorization", "")
            expected = f"Bearer {token}"
            if header != expected:
                return JSONResponse(
                    {"error": "unauthorized"},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
            return await call_next(request)

    app.add_middleware(BearerAuthMiddleware)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="The Bridge participants MCP server.")
    parser.add_argument(
        "--transport",
        choices=["http", "stdio"],
        default="http",
        help="http (remote, for ChatGPT/Claude connectors) or stdio (local clients). Default: http.",
    )
    parser.add_argument("--host", default=None, help="HTTP host (overrides HOST env).")
    parser.add_argument("--port", type=int, default=None, help="HTTP port (overrides PORT env).")
    parser.add_argument(
        "--path", default="/mcp", help="HTTP path the MCP endpoint is served at (default /mcp)."
    )
    args = parser.parse_args(argv)

    try:
        config = load_config()
    except RuntimeError as exc:
        parser.exit(2, f"Configuration error: {exc}\n")

    mcp = build_server(config)

    if args.transport == "stdio":
        mcp.run(transport="stdio")
        return

    host = args.host or config.host
    port = args.port or config.port

    if config.auth_token:
        import uvicorn

        app = mcp.http_app(path=args.path)
        _add_auth(app, config.auth_token)
        uvicorn.run(app, host=host, port=port)
    else:
        print(
            "WARNING: BRIDGE_MCP_TOKEN is not set — the server is unauthenticated. "
            "Anyone who can reach this URL can read participant data.",
            file=sys.stderr,
        )
        mcp.run(transport="http", host=host, port=port, path=args.path)


if __name__ == "__main__":
    main()
