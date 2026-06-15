# Next steps — finishing setup of the Bridge MCP

This file is a handoff so you can resume in a **new Claude Code session** and get
the server verified against the live Airtable base. The code is complete and
all offline tests pass; the only thing outstanding is a **live connection check**,
which was blocked in the previous session because the sandbox couldn't reach
`api.airtable.com` (network egress allowlist).

## Where things stand

- ✅ MCP server built: `src/bridge_mcp/` (tools: `search`, `fetch`, `list_participants`, `describe_table`).
- ✅ Schema-agnostic Airtable client with caching + optional bearer-token auth.
- ✅ 21 offline tests pass (`uv run pytest`).
- ✅ Base/table IDs pre-filled in `.env.example` (`apprmplt8X7rOIY6Z` / `tblktmVkEaIIKb00o`).
- ⏳ **Not yet done:** live verification against the real base (blocked by network egress).

## Step 1 — Allow outbound access to Airtable

The server calls Airtable's REST API directly from the sandbox, so the host must
be on the environment's egress allowlist.

When starting the new session, edit the **environment's Network access**:

1. Set network access to **Custom**.
2. In **Allowed domains**, add:
   ```
   api.airtable.com
   ```
3. Tick **"Also include default list of common package managers"** (keeps npm/uv/pip working).
4. Save, then start the session on branch **`claude/bridge-participant-mcp-188nts`**.

> Network-access changes generally apply to a **newly started** session, not a
> running one. If you can't find/edit this in the desktop app, use
> **claude.ai/code** in a browser, or just run the verification locally (Step 2,
> works on your laptop with no allowlist needed).

## Step 2 — Provide the token and run the verification

The PAT is a **secret** and is intentionally NOT stored in this repo. Set it as
an environment variable (don't commit it):

```bash
cp .env.example .env
# then edit .env and set AIRTABLE_API_KEY=<your Airtable PAT>

uv venv && uv pip install -e .
uv run python scripts/check_connection.py
```

`check_connection.py` exercises the full MCP path and prints:
- the table name and **every field** (so we confirm the chatbot sees the right data),
- the **participant count**,
- a live `search` + `fetch` round-trip.

A passing run ends with `ALL CHECKS PASSED ✅`. If credentials/access are wrong
you'll get a clear error (e.g. 401 = bad token/scopes, 403 = enterprise admin has
blocked PATs, 404 = base/table not shared with the token).

**Prompt to give the new session:** *"Run `uv run python scripts/check_connection.py`
to verify the live Airtable connection and report the schema."*

## Step 3 — Run the server and connect a chatbot

```bash
# Recommended: set BRIDGE_MCP_TOKEN in .env first (participant data is personal)
uv run bridge-mcp --transport http --host 0.0.0.0 --port 8000
# MCP endpoint: http://<host>:8000/mcp  (expose over public HTTPS for ChatGPT/Claude)
```

See `README.md` → **Connecting a chatbot** for the exact ChatGPT / Claude steps.

## Security reminders

- 🔑 **Rotate the PAT** that was pasted into the previous chat — treat it as compromised.
- 🔒 Always set `BRIDGE_MCP_TOKEN` before hosting publicly; the data is EF's and personal.
- ✅ Make sure you're cleared by EF to expose this participant data to a third-party chatbot.
