# edhrec-mcp Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python stdio MCP server exposing Scryfall card data and EDHREC Commander deckbuilding suggestions as five tools.

**Architecture:** Four decoupled layers — `http_cache` (httpx client + TTL disk cache), `scryfall` (card lookup/search), `edhrec` (slug-building + page parsing), `server` (FastMCP tool wrappers). The MCP layer knows nothing about HTTP; the data clients know nothing about MCP.

**Tech Stack:** Python 3.11+, `mcp[cli]` (FastMCP), `httpx`, `pytest`.

## Global Constraints

- **Python:** `requires-python >= 3.11` (uses `X | None` union syntax).
- **Dependencies (runtime):** only `mcp[cli]` and `httpx`. No `uv`, no `platformdirs`.
- **Dependencies (dev):** `pytest`. Tests use `httpx.MockTransport` — no network in unit tests.
- **Cache dir:** `Path.home() / ".cache" / "edhrec-mcp"`, overridable via env `EDHREC_MCP_CACHE_DIR`.
- **HTTP etiquette:** every request sends `User-Agent: edhrec-mcp/0.1` and `Accept: application/json`. Scryfall calls throttle to ≥100ms apart (`min_interval=0.1`; set to `0` in tests).
- **TTLs:** EDHREC pages `PAGE_TTL = 24*3600`; Scryfall cards `CARD_TTL = 12*3600`.
- **Commits:** every commit message ends with the trailer:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- **Package name:** `edhrec_mcp` (importable); distribution `edhrec-mcp`; console script `edhrec-mcp`.
- All Python is run from the repo's venv: `.venv/bin/python`, `.venv/bin/pytest`.

---

### Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `edhrec_mcp/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/test_smoke.py`

**Interfaces:**
- Consumes: nothing.
- Produces: an installed editable package `edhrec_mcp` with `mcp` and `httpx` importable; `.venv/` interpreter.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "edhrec-mcp"
version = "0.1.0"
description = "MCP server for Magic: The Gathering — Scryfall card data and EDHREC Commander suggestions"
requires-python = ">=3.11"
dependencies = [
    "mcp[cli]>=1.2",
    "httpx>=0.27",
]

[project.optional-dependencies]
dev = ["pytest>=8"]

[project.scripts]
edhrec-mcp = "edhrec_mcp.server:main"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["edhrec_mcp*"]

[tool.pytest.ini_options]
markers = ["network: hits live APIs; skipped unless explicitly selected"]
addopts = "-m 'not network'"
```

- [ ] **Step 2: Create empty package/test init files**

`edhrec_mcp/__init__.py`:
```python
"""MCP server for Magic: The Gathering (Scryfall + EDHREC)."""
__version__ = "0.1.0"
```

`tests/__init__.py`: empty file.

- [ ] **Step 3: Create venv and install**

Run:
```bash
python3 -m venv .venv
.venv/bin/pip install -q -e ".[dev]"
```
Expected: installs `mcp`, `httpx`, `pytest` with no errors.

- [ ] **Step 4: Write the smoke test**

`tests/test_smoke.py`:
```python
def test_imports():
    import edhrec_mcp
    import mcp
    import httpx
    assert edhrec_mcp.__version__ == "0.1.0"
```

- [ ] **Step 5: Run the smoke test**

Run: `.venv/bin/pytest tests/test_smoke.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml edhrec_mcp tests
git commit -m "chore: scaffold edhrec-mcp package

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: DiskCache

**Files:**
- Create: `edhrec_mcp/http_cache.py`
- Test: `tests/test_disk_cache.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `DEFAULT_CACHE_DIR: Path`
  - `class DiskCache(cache_dir: Path = DEFAULT_CACHE_DIR)` with
    `get(key: str, ttl: float, *, now: float | None = None) -> dict | None` and
    `set(key: str, data: dict, *, now: float | None = None) -> None`.
  - Injectable `now` makes TTL testable without sleeping. Entries stored as
    `<sha256(key)>.json` files containing `{"ts": float, "data": dict}`.

- [ ] **Step 1: Write the failing test**

`tests/test_disk_cache.py`:
```python
from edhrec_mcp.http_cache import DiskCache


def test_set_then_get_returns_data(tmp_path):
    cache = DiskCache(tmp_path)
    cache.set("http://x/y", {"a": 1}, now=1000.0)
    assert cache.get("http://x/y", ttl=100, now=1050.0) == {"a": 1}


def test_get_miss_returns_none(tmp_path):
    assert DiskCache(tmp_path).get("nope", ttl=100, now=0.0) is None


def test_expired_entry_returns_none(tmp_path):
    cache = DiskCache(tmp_path)
    cache.set("k", {"a": 1}, now=1000.0)
    assert cache.get("k", ttl=100, now=1200.0) is None


def test_corrupt_file_returns_none(tmp_path):
    cache = DiskCache(tmp_path)
    cache.set("k", {"a": 1}, now=1000.0)
    # Corrupt the underlying file
    next(tmp_path.glob("*.json")).write_text("{ not json")
    assert cache.get("k", ttl=100, now=1000.0) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_disk_cache.py -v`
Expected: FAIL with `ModuleNotFoundError: edhrec_mcp.http_cache`.

- [ ] **Step 3: Write minimal implementation**

`edhrec_mcp/http_cache.py`:
```python
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

DEFAULT_CACHE_DIR = Path(
    os.environ.get("EDHREC_MCP_CACHE_DIR", str(Path.home() / ".cache" / "edhrec-mcp"))
)


class DiskCache:
    def __init__(self, cache_dir: Path = DEFAULT_CACHE_DIR) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode()).hexdigest()
        return self.cache_dir / f"{digest}.json"

    def get(self, key: str, ttl: float, *, now: float | None = None) -> dict | None:
        now = time.time() if now is None else now
        path = self._path(key)
        if not path.exists():
            return None
        try:
            entry = json.loads(path.read_text())
        except (ValueError, OSError):
            return None
        if now - entry["ts"] > ttl:
            return None
        return entry["data"]

    def set(self, key: str, data: dict, *, now: float | None = None) -> None:
        now = time.time() if now is None else now
        self._path(key).write_text(json.dumps({"ts": now, "data": data}))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_disk_cache.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add edhrec_mcp/http_cache.py tests/test_disk_cache.py
git commit -m "feat: add TTL disk cache

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: JsonFetcher

**Files:**
- Modify: `edhrec_mcp/http_cache.py` (append `JsonFetcher`)
- Test: `tests/test_json_fetcher.py`

**Interfaces:**
- Consumes: `DiskCache` from Task 2.
- Produces:
  - `class JsonFetcher(cache: DiskCache, *, client: httpx.Client | None = None,
    user_agent: str = "edhrec-mcp/0.1", min_interval: float = 0.1)` with
    `get_json(url: str, *, ttl: float, retries: int = 1) -> dict`.
  - Returns cached data when fresh. On miss: throttles, GETs, calls
    `raise_for_status()`, caches and returns `resp.json()`. Retries only on
    `httpx.TransportError`/`httpx.TimeoutException` (up to `retries` extra
    attempts); lets `httpx.HTTPStatusError` propagate immediately (no retry).

- [ ] **Step 1: Write the failing test**

`tests/test_json_fetcher.py`:
```python
import httpx
import pytest

from edhrec_mcp.http_cache import DiskCache, JsonFetcher


def make_fetcher(tmp_path, handler):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return JsonFetcher(DiskCache(tmp_path), client=client, min_interval=0)


def test_fetches_and_returns_json(tmp_path):
    f = make_fetcher(tmp_path, lambda req: httpx.Response(200, json={"ok": True}))
    assert f.get_json("http://x/a", ttl=100) == {"ok": True}


def test_second_call_served_from_cache(tmp_path):
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(200, json={"n": calls["n"]})

    f = make_fetcher(tmp_path, handler)
    assert f.get_json("http://x/a", ttl=100) == {"n": 1}
    assert f.get_json("http://x/a", ttl=100) == {"n": 1}  # cached, handler not hit
    assert calls["n"] == 1


def test_http_error_propagates(tmp_path):
    f = make_fetcher(tmp_path, lambda req: httpx.Response(404, json={"e": 1}))
    with pytest.raises(httpx.HTTPStatusError):
        f.get_json("http://x/missing", ttl=100)


def test_retries_transport_error_then_succeeds(tmp_path):
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("boom", request=req)
        return httpx.Response(200, json={"ok": True})

    f = make_fetcher(tmp_path, handler)
    assert f.get_json("http://x/a", ttl=100, retries=1) == {"ok": True}
    assert calls["n"] == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_json_fetcher.py -v`
Expected: FAIL with `ImportError: cannot import name 'JsonFetcher'`.

- [ ] **Step 3: Write minimal implementation**

Append to `edhrec_mcp/http_cache.py` (add `import httpx` to the top imports):
```python
import httpx


class JsonFetcher:
    def __init__(
        self,
        cache: DiskCache,
        *,
        client: httpx.Client | None = None,
        user_agent: str = "edhrec-mcp/0.1",
        min_interval: float = 0.1,
    ) -> None:
        self.cache = cache
        self.min_interval = min_interval
        self._last_request = 0.0
        self.client = client or httpx.Client(
            timeout=20.0,
            headers={"User-Agent": user_agent, "Accept": "application/json"},
            follow_redirects=True,
        )

    def _throttle(self) -> None:
        if self.min_interval <= 0:
            return
        elapsed = time.time() - self._last_request
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_request = time.time()

    def get_json(self, url: str, *, ttl: float, retries: int = 1) -> dict:
        cached = self.cache.get(url, ttl)
        if cached is not None:
            return cached
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            try:
                self._throttle()
                resp = self.client.get(url)
                resp.raise_for_status()
                data = resp.json()
                self.cache.set(url, data)
                return data
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_exc = exc
        raise last_exc  # type: ignore[misc]
```

Note: `httpx.HTTPStatusError` is **not** a `TransportError`, so it propagates out of the loop immediately on the first attempt — exactly the wanted behavior.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_json_fetcher.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add edhrec_mcp/http_cache.py tests/test_json_fetcher.py
git commit -m "feat: add caching JSON fetcher with retry and throttle

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Scryfall client

**Files:**
- Create: `edhrec_mcp/scryfall.py`
- Test: `tests/test_scryfall.py`

**Interfaces:**
- Consumes: `JsonFetcher.get_json(url, *, ttl)` from Task 3.
- Produces:
  - `@dataclass Card(name: str, mana_cost: str, type_line: str, oracle_text: str,
    color_identity: list[str], commander_legal: bool, price_usd: str | None,
    image_url: str | None, set_name: str)`
  - `class CardNotFoundError(Exception)` with `.suggestion: str | None`
  - `_parse_card(d: dict) -> Card` (handles double-faced cards)
  - `class ScryfallClient(fetcher: JsonFetcher)` with
    `get_card(name: str) -> Card` and `search_cards(query: str, limit: int = 20) -> list[Card]`.

- [ ] **Step 1: Write the failing test**

`tests/test_scryfall.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_scryfall.py -v`
Expected: FAIL with `ModuleNotFoundError: edhrec_mcp.scryfall`.

- [ ] **Step 3: Write minimal implementation**

`edhrec_mcp/scryfall.py`:
```python
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


class CardNotFoundError(Exception):
    def __init__(self, message: str, suggestion: str | None = None) -> None:
        super().__init__(message)
        self.suggestion = suggestion


def _face_value(d: dict, key: str) -> str:
    top = d.get(key)
    if top:
        return top
    faces = d.get("card_faces") or []
    parts = [f.get(key, "") for f in faces if f.get(key)]
    return "\n//\n".join(parts)


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_scryfall.py -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add edhrec_mcp/scryfall.py tests/test_scryfall.py
git commit -m "feat: add Scryfall card lookup and search client

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: EDHREC client — slug, recommendations, themes

**Files:**
- Create: `edhrec_mcp/edhrec.py`
- Test: `tests/test_edhrec.py`

**Interfaces:**
- Consumes: `JsonFetcher.get_json(url, *, ttl)` from Task 3.
- Produces:
  - `slugify(name: str) -> str`
  - `@dataclass Recommendation(name, slug, synergy: float, inclusion: int, num_decks: int, potential_decks: int)`
  - `@dataclass CardList(header: str, tag: str, cards: list[Recommendation])`
  - `@dataclass CommanderRecommendations(commander: str, slug: str, cardlists: list[CardList])`
  - `@dataclass Theme(name: str, slug: str, count: int)`
  - `class CommanderNotFoundError(Exception)`
  - `class EdhrecClient(fetcher: JsonFetcher)` with
    `get_recommendations(commander: str, theme: str | None = None, budget: str | None = None) -> CommanderRecommendations`
    and `list_themes(commander: str) -> list[Theme]`.
  - `_commander_url(slug, theme, budget) -> str` builds
    `…/pages/commanders/<slug>[/<theme>][/<budget>].json`.

- [ ] **Step 1: Write the failing test**

`tests/test_edhrec.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_edhrec.py -v`
Expected: FAIL with `ModuleNotFoundError: edhrec_mcp.edhrec`.

- [ ] **Step 3: Write minimal implementation**

`edhrec_mcp/edhrec.py`:
```python
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
    no_punct = re.sub(r"[',’.]", "", lowered)
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_edhrec.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add edhrec_mcp/edhrec.py tests/test_edhrec.py
git commit -m "feat: add EDHREC recommendations and themes client

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: EDHREC average decklist

**Files:**
- Modify: `edhrec_mcp/edhrec.py` (add `get_average_decklist`)
- Test: `tests/test_edhrec_decklist.py`

**Interfaces:**
- Consumes: `slugify`, `_fetch_page`, `EdhrecClient` from Task 5.
- Produces: `EdhrecClient.get_average_decklist(commander: str, theme: str | None = None,
  budget: str | None = None) -> list[str]` — returns plain card names with the
  leading `"1 "` quantity prefix stripped. Uses the `average-decks` section URL.

- [ ] **Step 1: Write the failing test**

`tests/test_edhrec_decklist.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_edhrec_decklist.py -v`
Expected: FAIL with `AttributeError: 'EdhrecClient' object has no attribute 'get_average_decklist'`.

- [ ] **Step 3: Write minimal implementation**

Add a helper near `_commander_url` in `edhrec_mcp/edhrec.py`:
```python
def _average_deck_url(slug: str, theme: str | None, budget: str | None) -> str:
    parts = [slug]
    if theme:
        parts.append(theme)
    if budget:
        parts.append(budget)
    return f"{EDHREC_BASE}/average-decks/{'/'.join(parts)}.json"


def _strip_quantity(entry: str) -> str:
    return re.sub(r"^\d+\s+", "", entry).strip()
```

Add this method to `EdhrecClient`:
```python
    def get_average_decklist(
        self, commander: str, theme: str | None = None, budget: str | None = None
    ) -> list[str]:
        slug = slugify(commander)
        url = _average_deck_url(slug, theme, budget)
        data = _fetch_page(self.fetcher, url, commander)
        return [_strip_quantity(entry) for entry in data.get("deck", [])]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_edhrec_decklist.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add edhrec_mcp/edhrec.py tests/test_edhrec_decklist.py
git commit -m "feat: add EDHREC average decklist

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: FastMCP server and tools

**Files:**
- Create: `edhrec_mcp/server.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: `ScryfallClient`, `Card`, `CardNotFoundError` (Task 4);
  `EdhrecClient`, `CommanderNotFoundError` (Tasks 5–6); `DiskCache`, `JsonFetcher` (Tasks 2–3).
- Produces: module-level `mcp: FastMCP`, `scryfall: ScryfallClient`, `edhrec: EdhrecClient`
  (the last two are module globals so tests can replace them with fakes), five
  `@mcp.tool()` functions, and `main() -> None` which runs `mcp.run()`.
- Tool functions resolve a commander's canonical name via `scryfall.get_card`
  before querying EDHREC, returning JSON-serializable dicts.

- [ ] **Step 1: Write the failing test**

`tests/test_server.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_server.py -v`
Expected: FAIL with `ModuleNotFoundError: edhrec_mcp.server`.

- [ ] **Step 3: Write minimal implementation**

`edhrec_mcp/server.py`:
```python
from __future__ import annotations

from dataclasses import asdict

from mcp.server.fastmcp import FastMCP

from edhrec_mcp.edhrec import CommanderNotFoundError, EdhrecClient
from edhrec_mcp.http_cache import DiskCache, JsonFetcher
from edhrec_mcp.scryfall import CardNotFoundError, ScryfallClient

mcp = FastMCP("edhrec-mcp")

_fetcher = JsonFetcher(DiskCache())
scryfall = ScryfallClient(_fetcher)
edhrec = EdhrecClient(_fetcher)


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
    commander: str, theme: str | None = None, budget: str | None = None
) -> dict:
    """EDHREC card recommendations for a Commander.

    Optional `theme` is a theme slug from list_commander_themes (e.g. 'infect').
    Optional `budget` is 'budget' or 'expensive'. Returns card lists (top cards,
    high-synergy cards, game changers, by type) with synergy and inclusion stats.
    """
    try:
        canonical = _resolve_commander(commander)
    except CardNotFoundError as err:
        return {"error": f"Unknown commander {commander!r}. {err.suggestion or ''}".strip()}
    try:
        recs = edhrec.get_recommendations(canonical, theme=theme, budget=budget)
    except CommanderNotFoundError as err:
        return {"error": str(err)}
    return {
        "commander": recs.commander,
        "slug": recs.slug,
        "cardlists": [
            {"header": cl.header, "tag": cl.tag, "cards": [asdict(c) for c in cl.cards]}
            for cl in recs.cardlists
        ],
    }


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
    """
    try:
        canonical = _resolve_commander(commander)
    except CardNotFoundError as err:
        return {"error": f"Unknown commander {commander!r}. {err.suggestion or ''}".strip()}
    try:
        deck = edhrec.get_average_decklist(canonical, theme=theme, budget=budget)
    except CommanderNotFoundError as err:
        return {"error": str(err)}
    return {"commander": canonical, "count": len(deck), "deck": deck}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_server.py -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/pytest -v`
Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add edhrec_mcp/server.py tests/test_server.py
git commit -m "feat: add FastMCP server with five MTG tools

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Entry point verification, docs, and network smoke test

**Files:**
- Create: `README.md`
- Create: `tests/test_network.py`

**Interfaces:**
- Consumes: the `edhrec-mcp` console script (Task 1) and `server.main` (Task 7).
- Produces: a runnable server, a README with setup + MCP registration, and
  network-gated end-to-end tests (skipped by default via the `not network` addopt).

- [ ] **Step 1: Verify the server starts and lists tools over stdio**

Run:
```bash
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"smoke","version":"0"}}}' | .venv/bin/edhrec-mcp 2>/dev/null | head -c 200
```
Expected: a JSON-RPC response line containing `"serverInfo"` and `"edhrec-mcp"` (server initialized successfully, then exits on closed stdin).

- [ ] **Step 2: Write network-gated end-to-end tests**

`tests/test_network.py`:
```python
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
```

- [ ] **Step 3: Run the network tests explicitly**

Run: `.venv/bin/pytest tests/test_network.py -m network -v`
Expected: PASS (3 tests). (If offline, this step may be skipped — note it.)

- [ ] **Step 4: Write the README**

`README.md`:
```markdown
# edhrec-mcp

An MCP server for Magic: The Gathering, focused on Commander (EDH). It exposes
authoritative card data from [Scryfall](https://scryfall.com) and community
deckbuilding suggestions from [EDHREC](https://edhrec.com).

## Tools

- `get_card(name)` — card details: oracle text, mana cost, type, color identity,
  Commander legality, USD price, image.
- `search_cards(query, limit=20)` — Scryfall query-syntax search.
- `get_commander_recommendations(commander, theme=None, budget=None)` — EDHREC
  recommended cards (top, high-synergy, game changers, by type) with stats.
- `list_commander_themes(commander)` — available themes/archetypes with counts.
- `get_average_decklist(commander, theme=None, budget=None)` — the typical ~99 cards.

`theme` is a slug from `list_commander_themes` (e.g. `infect`). `budget` is
`budget` or `expensive`.

## Install

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

## Run

```bash
.venv/bin/edhrec-mcp
```

## Register with Claude Code

```bash
claude mcp add edhrec -- /absolute/path/to/.venv/bin/edhrec-mcp
```

Or add to an MCP client config:

```json
{
  "mcpServers": {
    "edhrec": {
      "command": "/absolute/path/to/.venv/bin/edhrec-mcp"
    }
  }
}
```

## Data & caching

Responses are cached under `~/.cache/edhrec-mcp/` (override with
`EDHREC_MCP_CACHE_DIR`): EDHREC pages 24h, Scryfall cards 12h. Prices may
therefore be up to 12h stale. EDHREC has no official API; this server reads its
public JSON endpoints politely (identifying User-Agent, throttled requests).

## Development

```bash
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest                      # unit tests (no network)
.venv/bin/pytest -m network           # live integration tests
```
```

- [ ] **Step 5: Commit**

```bash
git add README.md tests/test_network.py
git commit -m "docs: add README and live integration tests

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Notes for the implementer

- The cache directory is created at import time of `server.py` (via `DiskCache()`).
  In tests for `server.py` this is harmless; the directory is the real user cache
  dir. Unit tests for the clients always pass an explicit `tmp_path` cache.
- `theme` + `budget` combine as successive path segments
  (`/commanders/<slug>/<theme>/<budget>.json`). If EDHREC 404s an uncommon
  combination, the tool returns a clean "no page" error — acceptable.
- Throttle timing (`min_interval`) is not unit-tested; tests set it to `0`.
  The live `JsonFetcher()` default of `0.1s` applies in production.
