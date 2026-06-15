"""Quick live connection check for the Bridge MCP server.

Reads AIRTABLE_API_KEY / AIRTABLE_BASE_ID / AIRTABLE_TABLE_NAME from the
environment (or .env), then exercises the full MCP path against the real base:
discover the schema, count records, and run search + fetch through the actual
FastMCP tools. Prints a readable report. Exits non-zero on failure.

Usage:
    uv run python scripts/check_connection.py
"""

from __future__ import annotations

import asyncio
import sys

from fastmcp import Client

from bridge_mcp.config import load_config
from bridge_mcp.server import build_server


async def _run() -> int:
    config = load_config()
    mcp = build_server(config)

    async with Client(mcp) as client:
        schema = await client.call_tool("describe_table", {})
        data = schema.data
        print(f"✓ Connected. Table: {data['table']!r}")
        print(f"  Primary field: {data['primary_field']!r}")
        print(f"  Fields ({len(data['fields'])}):")
        for f in data["fields"]:
            print(f"    - {f['name']} ({f['type']})")

        listing = (await client.call_tool("list_participants", {})).data
        print(f"\n✓ Participants in table: {listing['total']}")

        sample = (await client.call_tool("search", {"query": ""})).data["results"]
        print(f"✓ search('') returned {len(sample)} sample result(s).")
        if sample:
            first_id = sample[0]["id"]
            print(f"  e.g. {sample[0]['title']!r} ({first_id})")
            profile = (await client.call_tool("fetch", {"id": first_id})).data
            preview = profile["text"].replace("\n", " | ")[:200]
            print(f"✓ fetch({first_id}) -> {preview}")

    print("\nALL CHECKS PASSED ✅")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(_run()))
    except Exception as exc:  # noqa: BLE001 - surface any failure clearly
        print(f"CHECK FAILED ❌  {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
