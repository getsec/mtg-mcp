import os

import pytest

from edhrec_mcp import collection

HEADER = ("Binder Name,Binder Type,Name,Set code,Set name,Collector number,Foil,Rarity,"
          "Quantity,ManaBox ID,Scryfall ID,Purchase price\n")


def write(path, rows):
    path.write_text(HEADER + "".join(rows))
    return path


def test_load_sums_quantity_across_binders(tmp_path):
    p = write(tmp_path / "ManaBox_Collection.csv", [
        "my cards,binder,Sol Ring,C21,Commander,1,normal,uncommon,1,1,id-sol,0\n",
        "worldseed ,binder,Sol Ring,C21,Commander,1,normal,uncommon,2,1,id-sol,0\n",
        'my cards,binder,"Emeritus of Woe // Demonic Tutor",SOS,x,1,foil,rare,1,2,id-emw,0\n',
    ])
    cards = {c.scryfall_id: c for c in collection.load(p)}
    assert cards["id-sol"].quantity == 3
    assert cards["id-sol"].binders == ["my cards", "worldseed"]
    assert cards["id-emw"].foil is True


def test_card_key_matches_front_face():
    assert collection.card_key("Emeritus of Woe // Demonic Tutor") == "emeritus of woe"
    assert collection.card_key("Sol Ring") == "sol ring"


def test_find_csv_picks_newest(tmp_path):
    old = write(tmp_path / "ManaBox_Collection.csv", [])
    new = write(tmp_path / "ManaBox_Collection (1).csv", [])
    write(tmp_path / "worldseed.csv", [])
    os.utime(old, (1, 1))
    assert collection.find_csv(tmp_path) == new


def test_find_csv_missing(tmp_path):
    with pytest.raises(collection.CollectionNotFoundError):
        collection.find_csv(tmp_path)


def test_load_rejects_non_manabox_csv(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text("a,b\n1,2\n")
    with pytest.raises(collection.CollectionNotFoundError):
        collection.load(p)
