"""HTML / feed / sitemap extraction and publication-date handling."""

from datetime import datetime, timedelta, timezone

from bs4 import BeautifulSoup

from backend.app.collection.dates import IST, html_dates, parse_date, pdf_date
from backend.app.collection.extractors import extract_feed, extract_html, extract_sitemap
from backend.app.collection.urls import canonicalize

ARTICLE = """
<html><head><title>PM Awas Yojana Gramin List 2026</title>
<meta property="article:published_time" content="2024-03-05T10:00:00+05:30">
<meta property="article:modified_time" content="2026-10-01T08:00:00+05:30">
<link rel="canonical" href="https://news.example/pmay-gramin-list/">
<script type="application/ld+json">{"@type":"FAQPage","mainEntity":[{"@type":"Question","name":"Who is eligible for PMAY-G houses?"}]}</script>
</head><body>
<nav><a href="/pmay-gramin-list/page/2/" class="next">Next</a><a href="/about-us/">About</a></nav>
<article><p>The Pradhan Mantri Awas Yojana Gramin list has been published for all districts this year by the ministry.</p>
<p>Applicants can check their names on the official portal using the registration number and village details.</p></article>
<ol class="comment-list">
 <li class="comment even depth-1" id="comment-1"><article class="comment-body">
   <div class="comment-metadata"><time datetime="2017-01-24T15:56:47+05:30">Jan 24, 2017</time></div>
   <div class="comment-content"><p>My name is not in the PMAY gramin list, what should I do now?</p></div></article>
   <ol class="children"><li class="comment byuser bypostauthor depth-2" id="comment-2"><article class="comment-body">
     <div class="comment-metadata"><time datetime="2017-01-25T09:00:00+05:30">Jan 25, 2017</time></div>
     <div class="comment-content"><p>You can contact your gram panchayat office for the PMAY-G list.</p></div></article></li></ol>
 </li>
 <li class="comment odd depth-1" id="comment-3"><article class="comment-body">
   <div class="comment-content"><p>Undated comment asking about the awas yojana installment status.</p></div></article></li>
</ol>
<a href="https://other-site.example/pmay">external</a>
<a href="/pm-kisan-status-check/">PM Kisan status</a>
</body></html>
"""


def test_html_comments_have_their_own_dates_and_roles():
    ex = extract_html(ARTICLE, "https://news.example/pmay-gramin-list/")
    comments = [r for r in ex.records if r.method == "html_comment"]
    assert [r.role for r in comments] == ["discussion", "site_reply", "discussion"]
    assert comments[0].published.value == datetime(2017, 1, 24, 10, 26, 47, tzinfo=timezone.utc)
    assert comments[0].source_document_id == "comment-1"
    assert comments[2].published is None          # never substituted with page or crawl time


def test_html_page_metadata_and_faq():
    ex = extract_html(ARTICLE, "https://news.example/pmay-gramin-list/")
    assert ex.published.value == datetime(2024, 3, 5, 4, 30, tzinfo=timezone.utc)
    assert ex.modified.value.year == 2026
    assert ex.canonical_url == "https://news.example/pmay-gramin-list"
    faqs = [r for r in ex.records if r.role == "faq"]
    assert faqs and faqs[0].text == "Who is eligible for PMAY-G houses?"
    article = [r for r in ex.records if r.role == "article"]
    assert article and article[0].text.startswith("PM Awas Yojana Gramin List 2026.")
    assert "gram panchayat" not in article[0].text      # comments are not part of the article body


def test_html_links_same_site_relevant_and_pagination():
    ex = extract_html(ARTICLE, "https://news.example/pmay-gramin-list/")
    links = {u: m for u, m, _ in ex.links}
    # Links are returned exactly as published (absolute); canonical forms are only used for dedup.
    assert links.get("https://news.example/pmay-gramin-list/page/2/") == "pagination"
    assert links.get("https://news.example/pm-kisan-status-check/") == "internal_link"
    assert not any("other-site" in u for u in links)
    assert "https://news.example/about-us/" not in links   # not welfare-related


FEED = """<?xml version="1.0"?><rss version="2.0"><channel><title>Scheme news</title>
<item><title>PM Kisan 21st installment released</title><link>https://news.example/pm-kisan-21?utm_source=rss</link>
<description>&lt;p&gt;The installment was credited to farmers.&lt;/p&gt;</description>
<pubDate>Tue, 14 Oct 2025 06:30:00 +0000</pubDate></item>
<item><title>Ujjwala refill subsidy extended for the year</title><link>https://news.example/ujjwala</link></item>
</channel></rss>"""


def test_feed_entries_dates_and_links():
    ex = extract_feed(FEED, "https://news.example/feed/")
    assert len(ex.records) == 2 and all(r.role == "news" for r in ex.records)
    assert ex.records[0].published.value == datetime(2025, 10, 14, 6, 30, tzinfo=timezone.utc)
    assert ex.records[0].source_url == "https://news.example/pm-kisan-21"   # tracking params dropped
    assert ex.records[0].text == "PM Kisan 21st installment released. The installment was credited to farmers."
    assert ex.records[1].published is None
    assert [m for _, m, _ in ex.links] == ["rss", "rss"]


SITEMAP = """<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://news.example/old-pmay-story</loc><lastmod>2023-01-01</lastmod></url>
<url><loc>https://news.example/new-pm-kisan-story</loc><lastmod>2026-09-01</lastmod></url>
<url><loc>https://news.example/cricket-score</loc><lastmod>2026-10-01</lastmod></url>
</urlset>"""


def test_sitemap_filters_relevant_and_orders_by_recency():
    ex = extract_sitemap(SITEMAP, "https://news.example/sitemap.xml")
    assert [u for u, _, _ in ex.links] == ["https://news.example/new-pm-kisan-story",
                                            "https://news.example/old-pmay-story"]  # cricket filtered out


def test_sitemap_index_links():
    idx = """<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <sitemap><loc>https://news.example/post-sitemap.xml</loc></sitemap></sitemapindex>"""
    assert extract_sitemap(idx, "https://news.example/sitemap.xml").links == [
        ("https://news.example/post-sitemap.xml", "sitemap_index", "")]


# ── Dates ─────────────────────────────────────────────────────────────────

def test_naive_dates_assume_ist_and_record_it():
    d = parse_date("2024-01-15 10:00", "meta:date")
    assert d.value == datetime(2024, 1, 15, 4, 30, tzinfo=timezone.utc) and "IST assumed" in d.source


def test_implausible_dates_rejected():
    assert parse_date((datetime.now(IST) + timedelta(days=30)).isoformat(), "x") is None
    assert parse_date("1975-01-01T00:00:00Z", "x") is None
    assert parse_date("not a date", "x") is None


def test_no_metadata_means_no_date():
    assert html_dates(BeautifulSoup("<html><body><p>hello</p></body></html>", "lxml")) == (None, None)


def test_pdf_date():
    d = pdf_date("D:20240115103000+05'30'", "pdf:CreationDate")
    assert d.value == datetime(2024, 1, 15, 5, 0, tzinfo=timezone.utc)


def test_canonicalize():
    assert canonicalize("HTTPS://Example.ORG:443/a/b/?utm_source=x&b=2&a=1#frag") == "https://example.org/a/b?a=1&b=2"
    assert canonicalize("javascript:alert(1)") is None
    assert canonicalize("/rel", base="https://example.org/x/") == "https://example.org/rel"
