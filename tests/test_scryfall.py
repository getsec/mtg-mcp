import httpx
import pytest

from edhrec_mcp.http_cache import DiskCache, JsonFetcher
from edhrec_mcp.scryfall import Card, CardNotFoundError, ScryfallClient, _parse_card

SOL_RING = {
    "name": "Sol Ring",
    "mana_cost": "{1}",
    "type_line": "Artifact",
    "oracle_text": "{T}: Add {C}{C}.",
    "color_identity": [],
    "legalities": {"commander": "legal"},
    "prices": {"usd": "4.73"},
    "image_uris": {"normal": "https://img/sol.jpg"},
    "set_name": "Commander 2021",
}

DFC = {
    "name": "Valki, God of Lies // Tibalt, Cosmic Impostor",
    "color_identity": ["B", "R"],
    "type_line": "Legendary Creature — God // Legendary Planeswalker — Tibalt",
    "legalities": {"commander": "legal"},
    "prices": {"usd": None},
    "set_name": "Kaldheim",
    "card_faces": [
        {"oracle_text": "Front text", "mana_cost": "{B}",
         "image_uris": {"normal": "https://img/valki.jpg"}},
        {"oracle_text": "Back text", "mana_cost": "{5}{R}{R}"},
    ],
}


def test_parse_simple_card():
    c = _parse_card(SOL_RING)
    assert c == Card(
        name="Sol Ring", mana_cost="{1}", type_line="Artifact",
        oracle_text="{T}: Add {C}{C}.", color_identity=[], commander_legal=True,
        price_usd="4.73", image_url="https://img/sol.jpg", set_name="Commander 2021",
    )


def test_parse_double_faced_card():
    c = _parse_card(DFC)
    assert "Front text" in c.oracle_text and "Back text" in c.oracle_text
    assert c.mana_cost == "{B}"
    assert c.image_url == "https://img/valki.jpg"
    assert c.commander_legal is True


def make_client(tmp_path, handler):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return ScryfallClient(JsonFetcher(DiskCache(tmp_path), client=client, min_interval=0))


def test_get_card_exact(tmp_path):
    sc = make_client(tmp_path, lambda req: httpx.Response(200, json=SOL_RING))
    assert sc.get_card("Sol Ring").name == "Sol Ring"


def test_get_card_falls_back_to_fuzzy(tmp_path):
    def handler(req):
        if "exact=" in str(req.url):
            return httpx.Response(404, json={"details": "no exact"})
        return httpx.Response(200, json=SOL_RING)

    sc = make_client(tmp_path, handler)
    assert sc.get_card("sol rng").name == "Sol Ring"


def test_get_card_not_found_raises_with_suggestion(tmp_path):
    def handler(req):
        return httpx.Response(404, json={"details": "Did you mean Sol Ring?"})

    sc = make_client(tmp_path, handler)
    with pytest.raises(CardNotFoundError) as exc:
        sc.get_card("xyzzy")
    assert "Sol Ring" in (exc.value.suggestion or "")


def test_search_returns_cards(tmp_path):
    body = {"data": [SOL_RING, SOL_RING, SOL_RING]}
    sc = make_client(tmp_path, lambda req: httpx.Response(200, json=body))
    out = sc.search_cards("t:artifact", limit=2)
    assert len(out) == 2 and out[0].name == "Sol Ring"


def test_search_no_results_returns_empty(tmp_path):
    sc = make_client(tmp_path, lambda req: httpx.Response(404, json={"details": "no cards"}))
    assert sc.search_cards("t:notreal") == []
