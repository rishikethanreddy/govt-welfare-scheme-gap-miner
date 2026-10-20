"""SSRF protection, redirect validation, limits, retries and robots.txt semantics.
All HTTP is served by httpx.MockTransport; nothing leaves the machine."""

import httpx
import pytest

from backend.app.collection.robots import RobotsPolicy
from backend.app.collection.safe_http import FetchError, SafeFetcher, UnsafeUrlError, UrlPolicy

PUBLIC_IP = "93.184.216.34"


def public_resolver(host):
    return {"internal.example": ["10.0.0.5"], "rebind.example": ["192.168.1.10"],
            "v6local.example": ["::1"]}.get(host, [PUBLIC_IP])


def fetcher(handler, robots=None, **kw):
    return SafeFetcher(policy=UrlPolicy(resolver=public_resolver), transport=httpx.MockTransport(handler),
                       robots=robots, default_delay=0, backoff_base=0.01, sleep=lambda s: None, **kw)


@pytest.mark.parametrize("url", [
    "http://localhost/admin",
    "http://127.0.0.1/",
    "http://10.1.2.3/",
    "http://169.254.169.254/latest/meta-data/",   # cloud metadata endpoint
    "http://[::1]/",
    "http://[::ffff:127.0.0.1]/",                  # IPv4-mapped IPv6 loopback
    "http://0.0.0.0/",
    "http://printer.local/",
    "http://internal.example/",                    # public-looking name resolving to a private IP
    "http://v6local.example/",
    "ftp://example.org/file",
    "file:///etc/passwd",
    "http://user:pass@example.org/",
    "http://example.org:8080/",
])
def test_unsafe_urls_rejected(url):
    with pytest.raises(UnsafeUrlError):
        UrlPolicy(resolver=public_resolver).check(url)


def test_public_url_allowed():
    assert UrlPolicy(resolver=public_resolver).check("https://example.org/page") == [PUBLIC_IP]


def test_redirect_to_private_address_is_blocked():
    def handler(req):
        if req.url.host == "example.org":
            return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"})
        return httpx.Response(200, text="secret")
    with fetcher(handler) as f, pytest.raises(UnsafeUrlError):
        f.fetch("https://example.org/start")


def test_redirect_to_hostname_resolving_privately_is_blocked():
    def handler(req):
        return httpx.Response(301, headers={"location": "http://rebind.example/x"})
    with fetcher(handler) as f, pytest.raises(UnsafeUrlError):
        f.fetch("https://example.org/start")


def test_safe_redirect_is_followed_and_recorded():
    def handler(req):
        if req.url.path == "/old":
            return httpx.Response(301, headers={"location": "/new"})
        return httpx.Response(200, text="<html>ok</html>", headers={"content-type": "text/html"})
    with fetcher(handler) as f:
        res = f.fetch("https://example.org/old")
    assert res.ok and res.final_url == "https://example.org/new" and res.redirects == ["https://example.org/old"]


def test_too_many_redirects():
    def handler(req):
        return httpx.Response(302, headers={"location": f"/loop{len(str(req.url))}"})
    with fetcher(handler) as f, pytest.raises(FetchError) as e:
        f.fetch("https://example.org/a")
    assert e.value.kind == "redirects"


def test_response_size_limit():
    def handler(req):
        return httpx.Response(200, content=b"x" * 5000, headers={"content-type": "text/html"})
    with fetcher(handler, max_bytes=1000) as f, pytest.raises(FetchError) as e:
        f.fetch("https://example.org/big")
    assert e.value.kind == "too_large"


def test_content_type_rejected():
    def handler(req):
        return httpx.Response(200, content=b"\x00\x01", headers={"content-type": "application/octet-stream"})
    with fetcher(handler) as f, pytest.raises(FetchError) as e:
        f.fetch("https://example.org/bin", accept=("text/html",))
    assert e.value.kind == "content_type"


def test_retries_with_backoff_then_success():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503)
        return httpx.Response(200, text="ok", headers={"content-type": "text/plain"})
    with fetcher(handler, max_retries=3) as f:
        assert f.fetch("https://example.org/flaky").ok
    assert calls["n"] == 3


def test_retries_exhausted_reports_failure():
    with fetcher(lambda req: httpx.Response(503), max_retries=1) as f, pytest.raises(FetchError) as e:
        f.fetch("https://example.org/down")
    assert e.value.kind == "http" and e.value.status == 503


def test_http_404_is_returned_not_retried():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(404)
    with fetcher(handler) as f:
        assert f.fetch("https://example.org/missing").status == 404
    assert calls["n"] == 1


def test_conditional_request_headers_and_304():
    def handler(req):
        assert req.headers.get("if-none-match") == '"abc"'
        return httpx.Response(304)
    with fetcher(handler) as f:
        assert f.fetch("https://example.org/p", etag='"abc"').not_modified


# ── robots.txt ────────────────────────────────────────────────────────────

def _robots_site(robots_status=200, robots_body="User-agent: *\nDisallow: /private\nCrawl-delay: 1\n"):
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(robots_status, text=robots_body, headers={"content-type": "text/plain"})
        return httpx.Response(200, text="<html>page</html>", headers={"content-type": "text/html"})
    return handler


def test_robots_disallow_is_enforced():
    robots = RobotsPolicy("WelfareAwarenessResearchBot/1.0")
    with fetcher(_robots_site(), robots=robots) as f:
        assert f.fetch("https://example.org/public").ok
        with pytest.raises(FetchError) as e:
            f.fetch("https://example.org/private/page")
    assert e.value.kind == "robots"


def test_robots_agent_specific_rules():
    body = "User-agent: WelfareAwarenessResearchBot\nDisallow: /\n\nUser-agent: *\nAllow: /\n"
    robots = RobotsPolicy("WelfareAwarenessResearchBot/1.0")
    with fetcher(_robots_site(robots_body=body), robots=robots) as f, pytest.raises(FetchError):
        f.fetch("https://example.org/anything")


def test_robots_404_means_allowed():
    robots = RobotsPolicy("WelfareAwarenessResearchBot/1.0")
    with fetcher(_robots_site(robots_status=404), robots=robots) as f:
        assert f.fetch("https://example.org/x").ok


def test_robots_unreachable_means_disallowed():
    robots = RobotsPolicy("WelfareAwarenessResearchBot/1.0")
    with fetcher(_robots_site(robots_status=500), robots=robots, max_retries=0) as f, pytest.raises(FetchError) as e:
        f.fetch("https://example.org/x")
    assert e.value.kind == "robots"
