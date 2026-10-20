"""
End-to-end collection against a mock website (no external requests):
robots.txt → RSS → article pages with comments → extraction → dedup → NLP → DB,
including a failing page, a robots-disallowed link, re-runs (unchanged content),
cancellation-safe status and timestamp integrity.
"""

import httpx
import pytest

from backend.app.collection.engine import CampaignRunner
from backend.app.collection.safe_http import HostRateLimiter, SafeFetcher, UrlPolicy
from backend.app.database import SessionLocal
from backend.app.models.crawl import CollectionCampaign, CollectionEvent, CrawlUrl
from backend.app.models.document import Document
from backend.app.models.source import Source, SourceRun

SITE = "https://schemes.example"

ROBOTS = "User-agent: *\nDisallow: /private/\n"

FEED = f"""<?xml version="1.0"?><rss version="2.0"><channel><title>Schemes</title>
<item><title>PMAY gramin list 2026 published</title><link>{SITE}/pmay-gramin-list/</link>
<pubDate>Mon, 13 Oct 2025 06:30:00 +0000</pubDate></item>
<item><title>PM Kisan installment date announced</title><link>{SITE}/pm-kisan-installment/</link>
<pubDate>Tue, 14 Oct 2025 06:30:00 +0000</pubDate></item>
<item><title>Mudra loan guide for small shop owners and vendors</title><link>{SITE}/mudra-loan-broken/</link></item>
</channel></rss>"""


def article(title, comments, extra=""):
    lis = "".join(
        f'<li class="comment" id="c{i}"><article class="comment-body"><time datetime="{when}">x</time>'
        f'<div class="comment-content"><p>{text}</p></div></article></li>' for i, (text, when) in enumerate(comments))
    return (f'<html><head><title>{title}</title><meta property="article:published_time" content="2025-10-13T09:00:00+05:30">'
            f'</head><body><article><p>{title} explained in detail for applicants across all districts of the country.</p>'
            f'<p>Eligibility, documents and the application process are described below for readers.</p></article>'
            f'<ol class="comment-list">{lis}</ol>{extra}</body></html>')


PAGES = {
    "/robots.txt": ("text/plain", ROBOTS),
    "/feed/": ("application/rss+xml", FEED),
    "/pmay-gramin-list/": ("text/html", article("PMAY Gramin List", [
        ("My name is not in the PMAY gramin list, how can I check why it was rejected?", "2017-01-24T15:56:47+05:30"),
        ("Am I eligible for a PMAY house if my father already owns a pucca house?", "2018-03-02T10:00:00+05:30"),
        ("My name is not in the PMAY gramin list, how can I check why it was rejected?", "2019-01-01T10:00:00+05:30"),
    ], extra=f'<a href="{SITE}/private/pmay-admin">admin</a>')),
    "/pm-kisan-installment/": ("text/html", article("PM Kisan installment", [
        ("When will the next PM Kisan installment be credited to my bank account?", "2024-06-01T08:00:00+05:30"),
        ("Call me on 9876543210 about the PM Kisan ekyc problem", "2024-06-02T08:00:00+05:30"),
    ])),
}


def handler(req: httpx.Request) -> httpx.Response:
    if req.url.host != "schemes.example":
        raise httpx.ConnectError("connection refused", request=req)
    path = req.url.path
    if path.rstrip("/") == "/mudra-loan-broken":
        return httpx.Response(500)
    if path.startswith("/private"):
        raise AssertionError("robots-disallowed URL must never be requested")
    # Like many real servers, only the exact published path exists (no slash redirects).
    if path not in PAGES:
        return httpx.Response(404)
    ctype, body = PAGES[path]
    return httpx.Response(200, text=body, headers={"content-type": ctype})


@pytest.fixture()
def source(db):
    s = Source(name="Mock scheme site", url=f"{SITE}/feed/", content_type="rss", source_type="publication",
               policy_status="allowed", active=True, max_pages=10, config={"follow_links": True},
               verification_status="configured")
    db.add(s)
    db.commit()
    return s


def run_campaign(source_ids, name="test"):
    db = SessionLocal()
    c = CollectionCampaign(name=name, source_ids=source_ids, status="queued", max_pages_per_source=10, max_depth=1)
    db.add(c)
    db.commit()
    cid = c.id
    db.close()
    runner = CampaignRunner(cid)
    runner.fetcher_factory = lambda: SafeFetcher(
        policy=UrlPolicy(resolver=lambda h: ["93.184.216.34"]), transport=httpx.MockTransport(handler),
        robots=runner.robots, rate_limiter=HostRateLimiter(), default_delay=0, max_retries=0,
        sleep=lambda s: None)
    return cid, runner.run()


def test_end_to_end_collection(db, source):
    cid, result = run_campaign([source.id])
    db.expire_all()
    c = db.get(CollectionCampaign, cid)
    # One page failed (HTTP 500) → the run is honest about partial success.
    assert result["status"] == "completed_with_errors" and c.status == "completed_with_errors"
    assert c.started_at and c.finished_at and c.finished_at >= c.started_at
    assert c.urls_failed == 1 and c.urls_processed == 4      # feed + 2 articles + 1 broken
    assert db.query(CrawlUrl).filter(CrawlUrl.url.contains("/private/")).count() == 0

    docs = db.query(Document).filter(Document.campaign_id == cid).all()
    comments = [d for d in docs if d.text_role == "discussion"]
    assert len(comments) == 4                                # 5 comments, 1 exact duplicate skipped
    assert c.records_duplicate >= 1 and c.records_final == len(docs) and c.records_processed == len(docs)
    assert all(d.processing_status == "completed" and d.origin == "live" for d in docs)
    # Timestamp integrity: comment dates come from the page, collection time is separate.
    first = next(d for d in comments if "why it was rejected" in d.original_text)
    assert first.source_published_at.year == 2017 and first.collected_at.year >= 2025
    news = [d for d in docs if d.text_role == "news"]
    assert {d.source_published_at.day for d in news if d.source_published_at} == {13, 14}
    assert any(d.source_published_at is None for d in news)  # the undated feed item stays undated
    assert all(d.awareness_gap == "not_applicable" for d in news)
    # PII redacted, provenance kept
    assert any("[PHONE]" in d.original_text for d in comments)
    assert all(d.source_id == source.id and d.crawl_page_id and d.source_url for d in docs)

    run = db.query(SourceRun).filter(SourceRun.campaign_id == cid).one()
    assert run.status == "completed_with_errors" and run.failed == 1 and run.records_accepted == len(docs)
    s = db.get(Source, source.id)
    assert s.verification_status == "collected" and s.last_success_at is not None
    kinds = {k for (k,) in db.query(CollectionEvent.kind).filter(CollectionEvent.campaign_id == cid).distinct()}
    assert {"stage", "fetch", "extract", "record", "summary"} <= kinds


def test_rerun_detects_unchanged_content(db, source):
    run_campaign([source.id], "first")
    cid, result = run_campaign([source.id], "second")
    db.expire_all()
    c = db.get(CollectionCampaign, cid)
    # Feed and both articles unchanged (same hash) → nothing re-extracted; the broken page fails again.
    assert c.urls_unchanged == 3 and c.urls_failed == 1
    assert c.records_final == 0           # nothing new, no duplicates created
    assert db.query(Document).filter(Document.campaign_id == cid).count() == 0


def test_unreachable_source_reports_failure(db):
    s = Source(name="Dead site", url="https://dead.example/feed/", content_type="rss", source_type="news",
               policy_status="allowed", active=True, max_pages=3, verification_status="configured")
    db.add(s)
    db.commit()
    cid, result = run_campaign([s.id])
    assert result["status"] == "failed"
    db.expire_all()
    assert db.get(Source, s.id).verification_status in ("failing", "blocked")
    assert db.get(Source, s.id).consecutive_failures == 1


def test_inactive_sources_are_not_collected(db, source):
    source.active = False
    db.commit()
    cid, result = run_campaign([source.id])
    assert result["status"] == "failed"
    assert db.query(CrawlUrl).filter(CrawlUrl.campaign_id == cid).count() == 0


def test_datagovin_seed_urls_use_filters_and_never_contain_the_key(db):
    from urllib.parse import parse_qs, urlsplit
    s = Source(name="KCC", url="https://api.data.gov.in/resource/", content_type="datagovin", source_type="open_data",
               policy_status="allowed", active=True, max_pages=3, verification_status="configured",
               config={"resource_id": "abc-123", "page_size": 50, "filters": {"QueryType": "Government Schemes"}})
    runner = CampaignRunner(1)
    urls = [u for u, _ in runner._seed_urls(s)]
    assert len(urls) == 3
    q = parse_qs(urlsplit(urls[1]).query)
    assert q["offset"] == ["50"] and q["limit"] == ["50"] and q["filters[QueryType]"] == ["Government Schemes"]
    assert all("api-key" not in u for u in urls)
