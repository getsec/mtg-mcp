import pytest

pytestmark = pytest.mark.network

from edhrec_mcp.edhrec import EdhrecClient
from edhrec_mcp.http_cache import DiskCache, JsonFetcher
from edhrec_mcp.scryfall import ScryfallClient


def _fetcher(tmp_path):
    return JsonFetcher(DiskCache(tmp_path))


def test_live_scryfall_sol_ring(tmp_path):
    card = ScryfallClient(_fetcher(tmp_path)).get_card("Sol Ring")
    assert card.name == "Sol Ring"
    assert card.commander_legal is True


def test_live_edhrec_recommendations(tmp_path):
    recs = EdhrecClient(_fetcher(tmp_path)).get_recommendations("Atraxa, Praetors' Voice")
    tags = {cl.tag for cl in recs.cardlists}
    assert "topcards" in tags


def test_live_edhrec_average_deck(tmp_path):
    deck = EdhrecClient(_fetcher(tmp_path)).get_average_decklist("Atraxa, Praetors' Voice")
    assert len(deck) > 50
