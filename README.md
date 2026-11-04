# edhrec-mcp

An MCP server for Magic: The Gathering, focused on Commander (EDH). It exposes
authoritative card data from [Scryfall](https://scryfall.com) and community
deckbuilding suggestions from [EDHREC](https://edhrec.com).

## Tools

- `get_card(name)` — card details: oracle text, mana cost, type, color identity,
  Commander legality, USD price, image.
- `search_cards(query, limit=20)` — Scryfall query-syntax search.
- `get_commander_recommendations(commander, theme=None, budget=None)` — EDHREC
  recommended cards (top, high-synergy, game changers, by type) with stats.
- `list_commander_themes(commander)` — available themes/archetypes with counts.
- `get_average_decklist(commander, theme=None, budget=None)` — the typical ~99 cards.
- `get_collection(colors=None, binder=None, type_contains=None, name_contains=None)` —
  your cards, from the newest ManaBox CSV export, with color identity and USD value.

## Your collection (ManaBox)

In ManaBox: Collection tab > top-right menu > Export > CSV. The newest
`ManaBox_Collection*.csv` in `~/Downloads` is used (override with
`EDHREC_MCP_COLLECTION`, a file or folder). Re-export whenever the collection
changes; nothing else to sync. When an export exists, recommendations get an
`owned` flag (plus `owned_only=True` to filter) and the average decklist gains
`owned` / `missing` lists.

`theme` is a slug from `list_commander_themes` (e.g. `infect`). `budget` is
`budget` or `expensive`.

## Install

Uses [uv](https://docs.astral.sh/uv/) for environment and dependency management.

```bash
uv sync
```

This creates `.venv/` and installs the project from the locked dependencies.

Without uv, you can use a standard virtualenv instead:

```bash
python3 -m venv .venv && .venv/bin/pip install -e .
```

## Run

```bash
uv run edhrec-mcp
```

## Register with Claude Code

```bash
claude mcp add edhrec -- uv run --directory /absolute/path/to/edhrec-mcp edhrec-mcp
```

Or add to an MCP client config:

```json
{
  "mcpServers": {
    "edhrec": {
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/edhrec-mcp", "edhrec-mcp"]
    }
  }
}
```

## Data & caching

Responses are cached under `~/.cache/edhrec-mcp/` (override with
`EDHREC_MCP_CACHE_DIR`): EDHREC pages 24h, Scryfall cards 12h. Prices may
therefore be up to 12h stale. EDHREC has no official API; this server reads its
public JSON endpoints politely (identifying User-Agent, throttled requests).

## Development

```bash
uv sync --extra dev          # install runtime + dev dependencies
uv run pytest                # unit tests (no network)
uv run pytest -m network     # live integration tests
```
