import httpx
import pytest

from edhrec_mcp.edhrec import (
    CommanderNotFoundError,
    EdhrecClient,
    Theme,
    slugify,
)
from edhrec_mcp.http_cache import DiskCache, JsonFetcher

COMMANDER_PAGE = {
    "container": {
        "json_dict": {
            "cardlists": [
                {
                    "header": "High Synergy Cards",
                    "tag": "highsynergycards",
                    "cardviews": [
                        {
                            "name": "Tezzeret's Gambit",
                            "sanitized": "tezzerets-gambit",
                            "synergy": 0.42,
                            "inclusion": 1200,
                            "num_decks": 1200,
                            "potential_decks": 2200,
                        }
                    ],
                },
                {
                    "header": "Top Cards",
                    "tag": "topcards",
                    "cardviews": [
                        {
                            "name": "Sol Ring",
                            "sanitized": "sol-ring",
                            "synergy": 0.0,
                            "inclusion": 2100,
                            "num_decks": 2100,
                            "potential_decks": 2200,
                        }
                    ],
                },
            ]
        }
    },
    "panels": {
        "taglinks": [
            {"value": "Infect", "slug": "infect", "count": 5092},
            {"value": "Proliferate", "slug": "proliferate", "count": 1274},
        ]
    },
}


def make_client(tmp_path, handler):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return EdhrecClient(JsonFetcher(DiskCache(tmp_path), client=client, min_interval=0))


def test_slugify_strips_punctuation():
    assert slugify("Atraxa, Praetors' Voice") == "atraxa-praetors-voice"
    assert slugify("Jenara, Asura of War") == "jenara-asura-of-war"


def test_slugify_uses_front_face_of_dfc():
    assert slugify("Valki, God of Lies // Tibalt, Cosmic Impostor") == "valki-god-of-lies"


def test_get_recommendations_parses_cardlists(tmp_path):
    ec = make_client(tmp_path, lambda req: httpx.Response(200, json=COMMANDER_PAGE))
    recs = ec.get_recommendations("Atraxa, Praetors' Voice")
    assert recs.slug == "atraxa-praetors-voice"
    assert [cl.tag for cl in recs.cardlists] == ["highsynergycards", "topcards"]
    top = recs.cardlists[0].cards[0]
    assert top.name == "Tezzeret's Gambit"
    assert top.synergy == 0.42
    assert top.inclusion == 1200


def test_recommendations_theme_builds_url(tmp_path):
    seen = {}

    def handler(req):
        seen["url"] = str(req.url)
        return httpx.Response(200, json=COMMANDER_PAGE)

    ec = make_client(tmp_path, handler)
    ec.get_recommendations("Atraxa, Praetors' Voice", theme="infect", budget="budget")
    assert seen["url"].endswith("/commanders/atraxa-praetors-voice/infect/budget.json")


def test_unknown_commander_raises(tmp_path):
    ec = make_client(tmp_path, lambda req: httpx.Response(404, json={"e": 1}))
    with pytest.raises(CommanderNotFoundError):
        ec.get_recommendations("Notacommander Xyz")


def test_list_themes(tmp_path):
    ec = make_client(tmp_path, lambda req: httpx.Response(200, json=COMMANDER_PAGE))
    themes = ec.list_themes("Atraxa, Praetors' Voice")
    assert themes[0] == Theme(name="Infect", slug="infect", count=5092)
    assert len(themes) == 2
