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

`theme` is a slug from `list_commander_themes` (e.g. `infect`). `budget` is
`budget` or `expensive`.

## Install

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

## Run

```bash
.venv/bin/edhrec-mcp
```

## Register with Claude Code

```bash
claude mcp add edhrec -- /absolute/path/to/.venv/bin/edhrec-mcp
```

Or add to an MCP client config:

```json
{
  "mcpServers": {
    "edhrec": {
      "command": "/absolute/path/to/.venv/bin/edhrec-mcp"
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
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest                      # unit tests (no network)
.venv/bin/pytest -m network           # live integration tests
```
