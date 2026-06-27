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
