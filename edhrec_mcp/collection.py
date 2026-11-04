"""Read a ManaBox collection CSV export (the newest one in a folder)."""
from __future__ import annotations

import csv
import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_SOURCE = Path(
    os.environ.get("EDHREC_MCP_COLLECTION", str(Path.home() / "Downloads"))
)
GLOB = "ManaBox_Collection*.csv"


class CollectionNotFoundError(Exception):
    pass


@dataclass
class OwnedCard:
    name: str
    scryfall_id: str
    quantity: int
    binders: list[str] = field(default_factory=list)
    foil: bool = False


def card_key(name: str) -> str:
    """Match key: front face, case-insensitive (EDHREC and ManaBox name DFCs differently)."""
    return name.split("//")[0].strip().lower()


def find_csv(source: Path | None = None) -> Path:
    source = Path(source or DEFAULT_SOURCE).expanduser()
    if source.is_file():
        return source
    files = sorted(source.glob(GLOB), key=lambda p: p.stat().st_mtime) if source.is_dir() else []
    if not files:
        raise CollectionNotFoundError(
            f"No {GLOB} found in {source}. Export the whole collection from ManaBox "
            "(Collection tab > menu > Export > CSV) or set EDHREC_MCP_COLLECTION."
        )
    return files[-1]


def load(path: Path) -> list[OwnedCard]:
    """One entry per printing (Scryfall ID), quantities summed across binders."""
    by_id: dict[str, OwnedCard] = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or "Scryfall ID" not in reader.fieldnames:
            raise CollectionNotFoundError(
                f"{path} is not a ManaBox export (no 'Scryfall ID' column)."
            )
        for row in reader:
            sid = row["Scryfall ID"].strip()
            if not sid:
                continue
            qty = int(row.get("Quantity") or 1)
            binder = (row.get("Binder Name") or "").strip()
            card = by_id.setdefault(sid, OwnedCard(name=row["Name"], scryfall_id=sid, quantity=0))
            card.quantity += qty
            card.foil = card.foil or row.get("Foil", "normal") != "normal"
            if binder and binder not in card.binders:
                card.binders.append(binder)
    return list(by_id.values())
