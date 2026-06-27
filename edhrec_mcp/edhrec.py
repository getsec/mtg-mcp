from __future__ import annotations

import re
from dataclasses import dataclass

import httpx

from edhrec_mcp.http_cache import JsonFetcher

EDHREC_BASE = "https://json.edhrec.com/pages"
PAGE_TTL = 24 * 3600


def slugify(name: str) -> str:
    front = name.split("//")[0]
    lowered = front.lower()
    no_punct = re.sub(r"['’.,]", "", lowered)
    hyphenated = re.sub(r"[^a-z0-9]+", "-", no_punct)
    return hyphenated.strip("-")


@dataclass
class Recommendation:
    name: str
    slug: str
    synergy: float
    inclusion: int
    num_decks: int
    potential_decks: int


@dataclass
class CardList:
    header: str
    tag: str
    cards: list[Recommendation]


@dataclass
class CommanderRecommendations:
    commander: str
    slug: str
    cardlists: list[CardList]


@dataclass
class Theme:
    name: str
    slug: str
    count: int


class CommanderNotFoundError(Exception):
    pass


def _commander_url(slug: str, theme: str | None, budget: str | None) -> str:
    parts = [slug]
    if theme:
        parts.append(theme)
    if budget:
        parts.append(budget)
    return f"{EDHREC_BASE}/commanders/{'/'.join(parts)}.json"


def _average_deck_url(slug: str, theme: str | None, budget: str | None) -> str:
    parts = [slug]
    if theme:
        parts.append(theme)
    if budget:
        parts.append(budget)
    return f"{EDHREC_BASE}/average-decks/{'/'.join(parts)}.json"


def _strip_quantity(entry: str) -> str:
    return re.sub(r"^\d+\s+", "", entry).strip()


def _fetch_page(fetcher: JsonFetcher, url: str, commander: str) -> dict:
    try:
        return fetcher.get_json(url, ttl=PAGE_TTL)
    except httpx.HTTPStatusError as err:
        if err.response.status_code == 404:
            raise CommanderNotFoundError(
                f"EDHREC has no page for {commander!r}. "
                "Verify the exact commander name with get_card."
            )
        raise


def _parse_recommendation(cv: dict) -> Recommendation:
    return Recommendation(
        name=cv["name"],
        slug=cv.get("sanitized", ""),
        synergy=cv.get("synergy", 0.0),
        inclusion=cv.get("inclusion", 0),
        num_decks=cv.get("num_decks", 0),
        potential_decks=cv.get("potential_decks", 0),
    )


class EdhrecClient:
    def __init__(self, fetcher: JsonFetcher) -> None:
        self.fetcher = fetcher

    def get_recommendations(
        self, commander: str, theme: str | None = None, budget: str | None = None
    ) -> CommanderRecommendations:
        slug = slugify(commander)
        url = _commander_url(slug, theme, budget)
        data = _fetch_page(self.fetcher, url, commander)
        raw_lists = data.get("container", {}).get("json_dict", {}).get("cardlists", [])
        cardlists = [
            CardList(
                header=cl.get("header", ""),
                tag=cl.get("tag", ""),
                cards=[_parse_recommendation(cv) for cv in cl.get("cardviews", [])],
            )
            for cl in raw_lists
        ]
        return CommanderRecommendations(commander=commander, slug=slug, cardlists=cardlists)

    def list_themes(self, commander: str) -> list[Theme]:
        slug = slugify(commander)
        url = _commander_url(slug, None, None)
        data = _fetch_page(self.fetcher, url, commander)
        taglinks = data.get("panels", {}).get("taglinks", [])
        return [
            Theme(name=t["value"], slug=t["slug"], count=t.get("count", 0))
            for t in taglinks
        ]

    def get_average_decklist(
        self, commander: str, theme: str | None = None, budget: str | None = None
    ) -> list[str]:
        slug = slugify(commander)
        url = _average_deck_url(slug, theme, budget)
        data = _fetch_page(self.fetcher, url, commander)
        return [_strip_quantity(entry) for entry in data.get("deck", [])]
