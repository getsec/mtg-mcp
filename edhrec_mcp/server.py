from __future__ import annotations

from dataclasses import asdict

import time

from mcp.server.fastmcp import FastMCP

from edhrec_mcp import collection

from edhrec_mcp.edhrec import CommanderNotFoundError, EdhrecClient
from edhrec_mcp.http_cache import DiskCache, JsonFetcher
from edhrec_mcp.scryfall import CardNotFoundError, ScryfallClient

mcp = FastMCP("edhrec-mcp")

_fetcher = JsonFetcher(DiskCache())
scryfall = ScryfallClient(_fetcher)
edhrec = EdhrecClient(_fetcher)


def _owned_keys() -> set[str] | None:
    """Names in the collection, or None when no export is available."""
    try:
        return {collection.card_key(c.name) for c in collection.load(collection.find_csv())}
    except collection.CollectionNotFoundError:
        return None


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
    commander: str, theme: str | None = None, budget: str | None = None,
    owned_only: bool = False,
) -> dict:
    """EDHREC card recommendations for a Commander.

    Optional `theme` is a theme slug from list_commander_themes (e.g. 'infect').
    Optional `budget` is 'budget' or 'expensive'. Returns card lists (top cards,
    high-synergy cards, game changers, by type) with synergy and inclusion stats.
    When a ManaBox collection export is available each card has `owned`;
    `owned_only=True` keeps just the cards you own.
    """
    try:
        canonical = _resolve_commander(commander)
    except CardNotFoundError as err:
        return {"error": f"Unknown commander {commander!r}. {err.suggestion or ''}".strip()}
    try:
        recs = edhrec.get_recommendations(canonical, theme=theme, budget=budget)
    except CommanderNotFoundError as err:
        return {"error": str(err)}
    owned = _owned_keys()
    if owned_only and owned is None:
        return {"error": "owned_only needs a ManaBox collection export; see get_collection."}
    cardlists = []
    for cl in recs.cardlists:
        cards = [asdict(c) for c in cl.cards]
        if owned is not None:
            for c in cards:
                c["owned"] = collection.card_key(c["name"]) in owned
            if owned_only:
                cards = [c for c in cards if c["owned"]]
        cardlists.append({"header": cl.header, "tag": cl.tag, "cards": cards})
    return {"commander": recs.commander, "slug": recs.slug, "cardlists": cardlists}


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
    When a ManaBox collection export is available, also splits the deck into
    `owned` and `missing` (what to buy).
    """
    try:
        canonical = _resolve_commander(commander)
    except CardNotFoundError as err:
        return {"error": f"Unknown commander {commander!r}. {err.suggestion or ''}".strip()}
    try:
        deck = edhrec.get_average_decklist(canonical, theme=theme, budget=budget)
    except CommanderNotFoundError as err:
        return {"error": str(err)}
    out = {"commander": canonical, "count": len(deck), "deck": deck}
    owned = _owned_keys()
    if owned is not None:
        out["owned"] = [n for n in deck if collection.card_key(n) in owned]
        out["missing"] = [n for n in deck if collection.card_key(n) not in owned]
    return out


@mcp.tool()
def get_collection(
    colors: str | None = None,
    binder: str | None = None,
    type_contains: str | None = None,
    name_contains: str | None = None,
) -> dict:
    """The user's card collection, from the newest ManaBox CSV export.

    Reads ManaBox_Collection*.csv from ~/Downloads (or EDHREC_MCP_COLLECTION,
    a file or folder). Filters: `colors` = a commander's color identity such
    as 'WB' (keeps cards playable under it; '' or 'C' = colorless only),
    `binder`, `type_contains` (e.g. 'Creature'), `name_contains`.
    Prices are Scryfall USD for the printing owned (foil price if foil).
    """
    try:
        path = collection.find_csv()
        owned = collection.load(path)
    except collection.CollectionNotFoundError as err:
        return {"error": str(err)}
    data = scryfall.get_cards_by_id([c.scryfall_id for c in owned])
    allowed = None if colors is None else set(colors.upper().replace("C", ""))
    merged: dict[str, dict] = {}
    for oc in owned:
        card = data.get(oc.scryfall_id)
        if card is None:
            continue
        if allowed is not None and not set(card.color_identity) <= allowed:
            continue
        if binder and binder.strip().lower() not in (b.lower() for b in oc.binders):
            continue
        if type_contains and type_contains.lower() not in card.type_line.lower():
            continue
        if name_contains and name_contains.lower() not in card.name.lower():
            continue
        price = card.price_usd_foil if oc.foil else card.price_usd
        entry = merged.setdefault(card.name, {
            "name": card.name, "quantity": 0, "binders": [],
            "color_identity": card.color_identity, "type_line": card.type_line,
            "mana_cost": card.mana_cost, "commander_legal": card.commander_legal,
            "value_usd": 0.0,
        })
        entry["quantity"] += oc.quantity
        entry["binders"] += [b for b in oc.binders if b not in entry["binders"]]
        entry["value_usd"] = round(entry["value_usd"] + float(price or 0) * oc.quantity, 2)
    cards = sorted(merged.values(), key=lambda c: c["name"])
    return {
        "source": str(path),
        "exported": time.strftime("%Y-%m-%d %H:%M", time.localtime(path.stat().st_mtime)),
        "unmatched_printings": sum(1 for c in owned if c.scryfall_id not in data),
        "unique_cards": len(cards),
        "total_quantity": sum(c["quantity"] for c in cards),
        "total_value_usd": round(sum(c["value_usd"] for c in cards), 2),
        "cards": cards,
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
