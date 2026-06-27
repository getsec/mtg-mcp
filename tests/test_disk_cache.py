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


def test_structurally_invalid_entry_returns_none(tmp_path):
    cache = DiskCache(tmp_path)
    cache.set("k", {"a": 1}, now=1000.0)
    # Overwrite with valid JSON that lacks the expected keys
    next(tmp_path.glob("*.json")).write_text('{"unexpected": true}')
    assert cache.get("k", ttl=100, now=1000.0) is None
