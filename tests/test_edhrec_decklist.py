import httpx
import pytest

from edhrec_mcp.edhrec import CommanderNotFoundError, EdhrecClient
from edhrec_mcp.http_cache import DiskCache, JsonFetcher

AVG_PAGE = {
    "deck": [
        "1 Atraxa, Praetors' Voice",
        "1 Arcane Signet",
        "1 Birds of Paradise",
    ]
}


def make_client(tmp_path, handler):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return EdhrecClient(JsonFetcher(DiskCache(tmp_path), client=client, min_interval=0))


def test_average_decklist_strips_quantity(tmp_path):
    seen = {}

    def handler(req):
        seen["url"] = str(req.url)
        return httpx.Response(200, json=AVG_PAGE)

    ec = make_client(tmp_path, handler)
    deck = ec.get_average_decklist("Atraxa, Praetors' Voice")
    assert deck == ["Atraxa, Praetors' Voice", "Arcane Signet", "Birds of Paradise"]
    assert seen["url"].endswith("/average-decks/atraxa-praetors-voice.json")


def test_average_decklist_theme_url(tmp_path):
    seen = {}

    def handler(req):
        seen["url"] = str(req.url)
        return httpx.Response(200, json=AVG_PAGE)

    ec = make_client(tmp_path, handler)
    ec.get_average_decklist("Atraxa, Praetors' Voice", theme="infect")
    assert seen["url"].endswith("/average-decks/atraxa-praetors-voice/infect.json")


def test_average_decklist_unknown_raises(tmp_path):
    ec = make_client(tmp_path, lambda req: httpx.Response(404, json={"e": 1}))
    with pytest.raises(CommanderNotFoundError):
        ec.get_average_decklist("Notacommander Xyz")
