# edhrec-mcp — Design

**Date:** 2026-06-26
**Status:** Approved

## Goal

A Model Context Protocol (MCP) server for Magic: The Gathering, focused on the
Commander (EDH) format. It exposes authoritative card data (Scryfall) and
EDHREC's community deckbuilding suggestions (recommended cards, themes, and the
typical decklist) as MCP tools an assistant can call.

## Scope

**In scope (focused core):**

- Card lookup and search via Scryfall.
- Commander recommendations, themes, and average decklists via EDHREC.

**Deferred (possible later iteration):** budget/expensive variant browsing as
first-class tools, combos, top-commanders lists, salt/staples lists, dedicated
price tools. (Theme and budget *filters* on the core EDHREC tools are included;
standalone discovery tools for them are deferred.)

## Data sources

EDHREC has no official API but serves the site from public JSON endpoints. Verified shapes (2026-06-26):

- **Commander page** — `https://json.edhrec.com/pages/commanders/<slug>.json`
  - `container.json_dict.cardlists[]` — buckets keyed by `tag`
    (`highsynergycards`, `topcards`, `gamechangers`, `creatures`, `instants`,
    `lands`, …). Each `cardviews[]` entry has `name`, `sanitized`, `synergy`,
    `inclusion`, `num_decks`, `potential_decks`.
  - `panels.taglinks[]` — themes, each `{value, slug, count}` (e.g. 185 themes).
  - `panels.combocounts`, `panels.mana_curve` — available, not parsed in core.
- **Average deck** — `https://json.edhrec.com/pages/average-decks/<slug>.json`
  - top-level `deck[]` — flat list of ~99 card names (the typical list).
- **Theme / budget variants** — `…/commanders/<slug>/<theme-slug>.json` and the
  budget variant pages.

**Scryfall** (official API, https://api.scryfall.com):

- `GET /cards/named?exact=` / `?fuzzy=` — single card (oracle text, mana cost,
  type line, legality, `prices`, image URIs).
- `GET /cards/search?q=` — query syntax search.
- Etiquette: send a `User-Agent` and `Accept: application/json`; throttle
  requests ~100ms apart.

## Architecture

Python stdio server on the official MCP SDK's `FastMCP`. Four layers, each
independently testable:

```
server.py      FastMCP instance + 5 tool definitions (thin wrappers; docstrings
               and type hints define the tool schemas)
edhrec.py      EDHREC client: slug building, fetch, parse JSON -> dataclasses
scryfall.py    Scryfall client: card lookup + search -> dataclasses
http_cache.py  shared httpx client + TTL disk cache; per-source throttle/headers
```

Each layer has one purpose and a narrow interface: `server` knows nothing about
HTTP; `edhrec`/`scryfall` know nothing about MCP; `http_cache` knows nothing
about MTG.

## Tools

| Tool | Source | Inputs | Returns |
|---|---|---|---|
| `get_card` | Scryfall | `name` (exact, falls back to fuzzy) | name, mana cost, type line, oracle text, color identity, legality (commander), price (usd), image URL, set |
| `search_cards` | Scryfall | `query` (Scryfall syntax), `limit` (default 20) | list of card summaries (name, mana cost, type, color identity, price) |
| `get_commander_recommendations` | EDHREC | `commander`, optional `theme`, optional `budget` ("budget"/"expensive") | top cards, high-synergy cards, game changers, and cards grouped by type — each with synergy %, inclusion count, deck counts |
| `list_commander_themes` | EDHREC | `commander` | themes/tags with deck counts (name, slug, count) |
| `get_average_decklist` | EDHREC | `commander`, optional `theme`, optional `budget` | the typical ~99-card list (card names, optionally grouped by type) |

## Data flow

1. A commander name is resolved through Scryfall fuzzy `named` first — this
   validates the card exists and yields the canonical name (handles typos).
2. The canonical name is sanitized to EDHREC's slug format: lowercase, strip
   apostrophes/commas/punctuation, collapse spaces to hyphens — matching the
   `sanitized` field observed in EDHREC responses.
3. The appropriate EDHREC endpoint (base, theme, or budget variant) is fetched
   through the cache, parsed into dataclasses, and returned.

## Caching

TTL disk cache under the user cache dir (`~/.cache/edhrec-mcp/`), keyed by a hash
of the request URL. EDHREC pages: 24h TTL. Scryfall card data: 12h TTL.
Persists across restarts, enables brief offline use, and cuts repeat requests.
Consequence: prices may be up to 12h stale — acceptable for deckbuilding.

## Error handling

- Unknown commander (EDHREC 404) → clear error suggesting the name be verified
  with `get_card`, since EDHREC slugs must match exactly.
- Card not found (Scryfall 404) → surface Scryfall's fuzzy suggestion if present.
- Network/timeout → one retry, then a readable error message.
- Never return a silent empty result that hides a failure.

## Testing

- `pytest` unit tests using the real JSON responses captured on 2026-06-26 as
  fixtures: slug-building, EDHREC/Scryfall parsing, and cache TTL behaviour, with
  HTTP mocked.
- A small number of network-gated integration tests (marker, skipped by default)
  that hit the live endpoints.

## Packaging & runtime

- PEP 621 `pyproject.toml`; dependencies `mcp[cli]` and `httpx` (plus
  `platformdirs` for the cache dir).
- Standard `venv` + `pip` install — no global tooling (no `uv`) required.
- Console entry point `edhrec-mcp` runs the stdio server.
- Ships with a `claude mcp add` / config snippet to register the server.
