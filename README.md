# Bridge MCP

An [MCP](https://modelcontextprotocol.io) server that turns an **Airtable**
base into a knowledge base your chatbot can talk to. It was built for
Entrepreneur First's **"The Bridge"** selection days: point it at the Airtable
that lists attendees, and people can then ask ChatGPT or Claude things like
*"who's working in fintech?"*, *"which founders want to meet ML engineers?"* or
*"tell me about Ada Lovelace's background"*.

It works with **both ChatGPT and Claude** because it runs as a remote
Streamable‑HTTP MCP server and implements the `search` + `fetch` tools that
ChatGPT's connectors require, alongside richer tools that Claude (and other MCP
clients) can use directly.

## What it exposes

| Tool | Purpose |
| --- | --- |
| `search(query)` | Free‑text search across every field. Returns `{id, title, url, text}` results. *(Required by ChatGPT.)* |
| `fetch(id)` | Full profile for one participant by id. Returns `{id, title, text, url, metadata}`. *(Required by ChatGPT.)* |
| `list_participants(limit)` | Everyone attending, with ids and deep links. |
| `describe_table()` | The table name and its available fields, so the model knows what it can ask about. |

The server is **schema‑agnostic**: it discovers the table's columns at runtime
via the Airtable Metadata API, so it keeps working if you rename, add or remove
fields. Access is strictly **read‑only**.

## Prerequisites

1. **An Airtable Personal Access Token (PAT).** Create one at
   <https://airtable.com/create/tokens> with these scopes:
   - `data.records:read`
   - `schema.bases:read`

   Grant the token access to the base that holds The Bridge participants.
2. **Your base ID.** Open the base in a browser — the URL is
   `https://airtable.com/appXXXXXXXXXXXXXX/...`; the `appXXXXXXXXXXXXXX` part is
   the base ID.
3. **Python 3.10+** (and ideally [`uv`](https://docs.astral.sh/uv/)).

## Setup

```bash
git clone <this-repo> && cd bridge-mcp
cp .env.example .env          # then fill in your Airtable details
uv venv && uv pip install -e .
```

Edit `.env`:

```dotenv
AIRTABLE_API_KEY=patXXXX...        # your PAT
AIRTABLE_BASE_ID=appXXXXXXXXXXXXXX # the base id
AIRTABLE_TABLE_NAME=Participants   # optional; defaults to the first table
BRIDGE_MCP_TOKEN=some-long-secret  # optional but recommended when hosting publicly
```

## Running it

**Remote / HTTP (for ChatGPT and Claude connectors):**

```bash
uv run bridge-mcp --transport http --host 0.0.0.0 --port 8000
# MCP endpoint: http://<host>:8000/mcp
```

**Local / stdio (for Claude Desktop, Cursor, etc.):**

```bash
uv run bridge-mcp --transport stdio
```

> ⚠️ **Participant data is personal.** When hosting over HTTP, set
> `BRIDGE_MCP_TOKEN`. Every request must then send
> `Authorization: Bearer <token>`, and the server refuses unauthenticated
> traffic. ChatGPT and Claude connectors let you supply this header when adding
> the connector. Without a token the server runs open and prints a warning.

To reach the internet you'll need a public HTTPS URL. For local testing you can
tunnel with e.g. [`ngrok`](https://ngrok.com): `ngrok http 8000`.

## Connecting a chatbot

### Claude (claude.ai / Claude Desktop — remote connector)

1. Settings → **Connectors** → **Add custom connector**.
2. URL: `https://<your-host>/mcp`.
3. If you set `BRIDGE_MCP_TOKEN`, add an `Authorization: Bearer <token>` header.

### Claude Desktop (local, stdio)

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "bridge": {
      "command": "uv",
      "args": ["run", "bridge-mcp", "--transport", "stdio"],
      "cwd": "/absolute/path/to/bridge-mcp"
    }
  }
}
```

### ChatGPT (custom connector / deep research)

ChatGPT only supports **remote** MCP servers, and requires the `search` and
`fetch` tools — both of which this server provides.

1. Enable **Developer mode / Connectors** (Settings → Connectors).
2. **Add custom connector** → paste `https://<your-host>/mcp`.
3. Supply the `Authorization: Bearer <token>` header if you set one.

The server must be reachable over public **HTTPS** for ChatGPT to accept it.

## Development

```bash
uv pip install -e ".[dev]"
uv run pytest
```

Tests are fully offline — the Airtable client is exercised with
`httpx.MockTransport` and the tools via FastMCP's in‑memory client, so no real
Airtable credentials or network access are needed.

### Project layout

```
src/bridge_mcp/
  config.py       # env-var configuration
  airtable.py     # schema-agnostic, cached, read-only Airtable client
  formatting.py   # record -> search-result / readable-text helpers
  server.py       # FastMCP server, tools, transports, optional auth
tests/            # offline unit + integration tests
```

## License

MIT — see [LICENSE](LICENSE).
