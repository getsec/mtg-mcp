from __future__ import annotations

from dataclasses import asdict

from mcp.server.fastmcp import FastMCP

from edhrec_mcp.edhrec import CommanderNotFoundError, EdhrecClient
from edhrec_mcp.http_cache import DiskCache, JsonFetcher
from edhrec_mcp.scryfall import CardNotFoundError, ScryfallClient

mcp = FastMCP("edhrec-mcp")

_fetcher = JsonFetcher(DiskCache())
scryfall = ScryfallClient(_fetcher)
edhrec = EdhrecClient(_fetcher)


def _resolve_commander(name: str) -> str:
    """Validate/canonicalize a commander name via Scryfall."""
    return scryfall.get_card(name).name


@mcp.tool()
def get_card(name: str) -> dict:
    """Look up a Magic card by name (exact, falling back to fuzzy match).

    Returns oracle text, mana cost, type line, color identity, Commander
    legality, USD price, image URL and set.
    """
    try:
        return asdict(scryfall.get_card(name))
    except CardNotFoundError as err:
        msg = str(err)
        if err.suggestion:
            msg += f" {err.suggestion}"
        return {"error": msg}


@mcp.tool()
def search_cards(query: str, limit: int = 20) -> dict:
    """Search for Magic cards using Scryfall query syntax.

    Example queries: 't:dragon c:r cmc<=4', 'o:"draw a card" t:instant'.
    """
    cards = scryfall.search_cards(query, limit=limit)
    return {"count": len(cards), "cards": [asdict(c) for c in cards]}


@mcp.tool()
def get_commander_recommendations(
    commander: str, theme: str | None = None, budget: str | None = None
) -> dict:
    """EDHREC card recommendations for a Commander.

    Optional `theme` is a theme slug from list_commander_themes (e.g. 'infect').
    Optional `budget` is 'budget' or 'expensive'. Returns card lists (top cards,
    high-synergy cards, game changers, by type) with synergy and inclusion stats.
    """
    try:
        canonical = _resolve_commander(commander)
    except CardNotFoundError as err:
        return {"error": f"Unknown commander {commander!r}. {err.suggestion or ''}".strip()}
    try:
        recs = edhrec.get_recommendations(canonical, theme=theme, budget=budget)
    except CommanderNotFoundError as err:
        return {"error": str(err)}
    return {
        "commander": recs.commander,
        "slug": recs.slug,
        "cardlists": [
            {"header": cl.header, "tag": cl.tag, "cards": [asdict(c) for c in cl.cards]}
            for cl in recs.cardlists
        ],
    }


@mcp.tool()
def list_commander_themes(commander: str) -> dict:
    """List EDHREC themes/archetypes available for a Commander, with deck counts."""
    try:
        canonical = _resolve_commander(commander)
    except CardNotFoundError as err:
        return {"error": f"Unknown commander {commander!r}. {err.suggestion or ''}".strip()}
    try:
        themes = edhrec.list_themes(canonical)
    except CommanderNotFoundError as err:
        return {"error": str(err)}
    return {"commander": canonical, "themes": [asdict(t) for t in themes]}


@mcp.tool()
def get_average_decklist(
    commander: str, theme: str | None = None, budget: str | None = None
) -> dict:
    """The typical ~99-card EDHREC decklist for a Commander.

    Optional `theme` (theme slug) and `budget` ('budget'/'expensive') narrow it.
    """
    try:
        canonical = _resolve_commander(commander)
    except CardNotFoundError as err:
        return {"error": f"Unknown commander {commander!r}. {err.suggestion or ''}".strip()}
    try:
        deck = edhrec.get_average_decklist(canonical, theme=theme, budget=budget)
    except CommanderNotFoundError as err:
        return {"error": str(err)}
    return {"commander": canonical, "count": len(deck), "deck": deck}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
