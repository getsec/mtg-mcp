import pytest

import edhrec_mcp.server as server
from edhrec_mcp.edhrec import (
    CardList,
    CommanderNotFoundError,
    CommanderRecommendations,
    Recommendation,
    Theme,
)
from edhrec_mcp.scryfall import Card, CardNotFoundError


class FakeScryfall:
    def __init__(self):
        self.card = Card(
            name="Atraxa, Praetors' Voice", mana_cost="{G}{W}{U}{B}",
            type_line="Legendary Creature", oracle_text="Flying...",
            color_identity=["B", "G", "U", "W"], commander_legal=True,
            price_usd="12.00", image_url="https://img/atx.jpg", set_name="C16",
        )

    def get_card(self, name):
        if name == "missing":
            raise CardNotFoundError("nope", suggestion="Try Atraxa")
        return self.card

    def search_cards(self, query, limit=20):
        return [self.card]


class FakeEdhrec:
    def get_recommendations(self, commander, theme=None, budget=None):
        return CommanderRecommendations(
            commander=commander, slug="atraxa-praetors-voice",
            cardlists=[CardList("Top Cards", "topcards", [
                Recommendation("Sol Ring", "sol-ring", 0.0, 2100, 2100, 2200)])],
        )

    def list_themes(self, commander):
        return [Theme("Infect", "infect", 5092)]

    def get_average_decklist(self, commander, theme=None, budget=None):
        return ["Sol Ring", "Arcane Signet"]


@pytest.fixture(autouse=True)
def fakes(monkeypatch):
    monkeypatch.setattr(server, "scryfall", FakeScryfall())
    monkeypatch.setattr(server, "edhrec", FakeEdhrec())


def test_get_card_tool():
    out = server.get_card("Sol Ring")
    assert out["name"] == "Atraxa, Praetors' Voice"
    assert out["commander_legal"] is True


def test_get_card_tool_not_found():
    out = server.get_card("missing")
    assert "error" in out and "Try Atraxa" in out["error"]


def test_search_cards_tool():
    out = server.search_cards("t:artifact")
    assert out["count"] == 1
    assert out["cards"][0]["name"] == "Atraxa, Praetors' Voice"


def test_recommendations_tool():
    out = server.get_commander_recommendations("Atraxa")
    assert out["slug"] == "atraxa-praetors-voice"
    assert out["cardlists"][0]["cards"][0]["name"] == "Sol Ring"


def test_recommendations_tool_unknown_commander():
    server.scryfall.get_card = lambda name: (_ for _ in ()).throw(
        CardNotFoundError("nope", suggestion=None))
    out = server.get_commander_recommendations("zzz")
    assert "error" in out


def test_themes_tool():
    out = server.list_commander_themes("Atraxa")
    assert out["themes"][0]["name"] == "Infect"


def test_average_decklist_tool():
    out = server.get_average_decklist("Atraxa")
    assert out["deck"] == ["Sol Ring", "Arcane Signet"]
    assert out["count"] == 2


def test_tools_registered():
    # All five tools are registered with the FastMCP instance.
    import asyncio
    tools = asyncio.run(server.mcp.list_tools())
    names = {t.name for t in tools}
    assert names == {
        "get_card", "search_cards", "get_commander_recommendations",
        "list_commander_themes", "get_average_decklist",
    }
