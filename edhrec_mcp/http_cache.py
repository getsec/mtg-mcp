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
