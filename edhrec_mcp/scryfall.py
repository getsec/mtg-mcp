from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from edhrec_mcp.http_cache import JsonFetcher

SCRYFALL_BASE = "https://api.scryfall.com"
CARD_TTL = 12 * 3600


@dataclass
class Card:
    name: str
    mana_cost: str
    type_line: str
    oracle_text: str
    color_identity: list[str]
    commander_legal: bool
    price_usd: str | None
    image_url: str | None
    set_name: str
    price_usd_foil: str | None = None


class CardNotFoundError(Exception):
    def __init__(self, message: str, suggestion: str | None = None) -> None:
        super().__init__(message)
        self.suggestion = suggestion


def _face_value(d: dict, key: str) -> str:
    top = d.get(key)
    if top:
        return top
    faces = d.get("card_faces") or []
    if not faces:
        return ""
    if key == "oracle_text":
        parts = [f.get(key, "") for f in faces if f.get(key)]
        return "\n//\n".join(parts)
    else:
        return faces[0].get(key, "")


def _image_url(d: dict) -> str | None:
    uris = d.get("image_uris")
    if uris:
        return uris.get("normal")
    for face in d.get("card_faces") or []:
        if face.get("image_uris"):
            return face["image_uris"].get("normal")
    return None


def _parse_card(d: dict) -> Card:
    return Card(
        name=d["name"],
        mana_cost=_face_value(d, "mana_cost"),
        type_line=d.get("type_line", ""),
        oracle_text=_face_value(d, "oracle_text"),
        color_identity=d.get("color_identity", []),
        commander_legal=d.get("legalities", {}).get("commander") == "legal",
        price_usd=(d.get("prices") or {}).get("usd"),
        image_url=_image_url(d),
        set_name=d.get("set_name", ""),
        price_usd_foil=(d.get("prices") or {}).get("usd_foil"),
    )


class ScryfallClient:
    def __init__(self, fetcher: JsonFetcher) -> None:
        self.fetcher = fetcher

    def get_card(self, name: str) -> Card:
        exact = f"{SCRYFALL_BASE}/cards/named?{urlencode({'exact': name})}"
        try:
            return _parse_card(self.fetcher.get_json(exact, ttl=CARD_TTL))
        except httpx.HTTPStatusError as err:
            if err.response.status_code != 404:
                raise
        fuzzy = f"{SCRYFALL_BASE}/cards/named?{urlencode({'fuzzy': name})}"
        try:
            return _parse_card(self.fetcher.get_json(fuzzy, ttl=CARD_TTL))
        except httpx.HTTPStatusError as err:
            if err.response.status_code != 404:
                raise
            detail = None
            try:
                detail = err.response.json().get("details")
            except Exception:
                pass
            raise CardNotFoundError(f"No card found for {name!r}.", suggestion=detail)

    def search_cards(self, query: str, limit: int = 20) -> list[Card]:
        url = f"{SCRYFALL_BASE}/cards/search?{urlencode({'q': query})}"
        try:
            data = self.fetcher.get_json(url, ttl=CARD_TTL)
        except httpx.HTTPStatusError as err:
            if err.response.status_code == 404:
                return []
            raise
        return [_parse_card(c) for c in data.get("data", [])[:limit]]

    def get_cards_by_id(self, ids: list[str]) -> dict[str, Card]:
        """Bulk lookup by Scryfall ID (75 per request); each card cached on disk."""
        cache = self.fetcher.cache
        out: dict[str, Card] = {}
        missing = []
        for sid in dict.fromkeys(ids):
            hit = cache.get(f"scryfall-id:{sid}", CARD_TTL)
            if hit is not None:
                out[sid] = _parse_card(hit)
            else:
                missing.append(sid)
        for i in range(0, len(missing), 75):
            body = {"identifiers": [{"id": sid} for sid in missing[i:i + 75]]}
            data = self.fetcher.post_json(f"{SCRYFALL_BASE}/cards/collection", body)
            for d in data.get("data", []):
                cache.set(f"scryfall-id:{d['id']}", d)
                out[d["id"]] = _parse_card(d)
        return out
