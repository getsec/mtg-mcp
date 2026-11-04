from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

import httpx

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
            if now - entry["ts"] > ttl:
                return None
            return entry["data"]
        except (ValueError, OSError, KeyError, TypeError):
            return None

    def set(self, key: str, data: dict, *, now: float | None = None) -> None:
        now = time.time() if now is None else now
        self._path(key).write_text(json.dumps({"ts": now, "data": data}))


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

    def post_json(self, url: str, body: dict, *, retries: int = 1) -> dict:
        """Uncached POST; callers cache the parts of the response they need."""
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            try:
                self._throttle()
                resp = self.client.post(url, json=body)
                resp.raise_for_status()
                return resp.json()
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_exc = exc
        raise last_exc  # type: ignore[misc]
