"""
Content extractors: HTML, RSS/Atom, sitemaps, PDF, JSON and CSV.

Each extractor returns ExtractedRecord objects plus discovered links. The text
role is assigned from *where* the text came from, not from its wording:
  discussion — user comments on a page (public voice)
  query      — records from a public query dataset (e.g. call-centre logs)
  faq        — question/answer entries authored by the site
  news       — feed entries / headlines
  article    — article body summaries
Only public-voice roles are later considered for awareness-gap detection.
"""

import csv
import io
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from bs4 import BeautifulSoup

from backend.app.collection.dates import DateInfo, html_dates, parse_date, pdf_date
from backend.app.collection.urls import absolute, canonicalize, is_crawlable_path, looks_relevant, same_site

MIN_RECORD_CHARS = 20
MAX_RECORD_CHARS = 5000


@dataclass
class ExtractedRecord:
    text: str
    role: str
    method: str
    source_url: str
    published: Optional[DateInfo] = None
    updated: Optional[DateInfo] = None
    title: Optional[str] = None
    source_document_id: Optional[str] = None
    state: Optional[str] = None
    district: Optional[str] = None
    metadata: dict = field(default_factory=dict)


@dataclass
class Extraction:
    records: list = field(default_factory=list)
    links: list = field(default_factory=list)       # [(url, method, anchor_text)]
    title: Optional[str] = None
    published: Optional[DateInfo] = None
    modified: Optional[DateInfo] = None
    canonical_url: Optional[str] = None
    page_type: str = "html"


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _ok(text: str) -> bool:
    return MIN_RECORD_CHARS <= len(text) <= MAX_RECORD_CHARS


# ── HTML ──────────────────────────────────────────────────────────────────

_COMMENT_CONTAINERS = ("div.comment", "li.comment", "article.comment")
_COMMENT_BODY = (".comment-content", ".comment-text", ".comment-body p")
_NOISE = "script, style, noscript, nav, header, footer, aside, form, iframe, .sidebar, .menu, .advertisement, .ads, .share"


def _faq_jsonld(soup, url) -> list:
    out = []
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except (ValueError, TypeError):
            continue
        stack = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
            elif isinstance(node, dict):
                if node.get("@type") == "Question" and node.get("name"):
                    out.append(_clean(BeautifulSoup(str(node["name"]), "lxml").get_text(" ")))
                stack.extend(v for v in node.values() if isinstance(v, (dict, list)))
    return out


def extract_html(html: str, url: str, max_links: int = 200) -> Extraction:
    soup = BeautifulSoup(html, "lxml")
    ex = Extraction(page_type="html")
    ex.title = _clean(soup.title.get_text()) if soup.title else None
    ex.published, ex.modified = html_dates(soup)
    link = soup.find("link", rel="canonical")
    if link and link.get("href"):
        c = canonicalize(link["href"], url)
        if c and same_site(c, url):
            ex.canonical_url = c

    # 1. User comments (public voice), each with its own timestamp when present.
    seen = set()
    for container in soup.select(", ".join(_COMMENT_CONTAINERS)):
        body = None
        for sel in _COMMENT_BODY:
            body = container.select_one(sel)
            if body:
                break
        if body is None:
            continue
        # Body selectors target the comment's own text block; replies are sibling
        # containers (WordPress puts them in ol.children), so they are not included.
        text = _clean(body.get_text(" "))
        if not _ok(text):  # repeated comments are kept so the pipeline counts them as duplicates
            continue
        seen.add(text)
        t = container.find("time")
        when = parse_date(t.get("datetime"), "comment time[datetime]") if t and t.get("datetime") else None
        cid = container.get("id")
        # WordPress marks replies written by the article's author; those are answers, not public voice.
        classes = set(container.get("class") or [])
        role = "site_reply" if classes & {"bypostauthor", "comment-author-admin"} else "discussion"
        ex.records.append(ExtractedRecord(text=text, role=role, method="html_comment", source_url=url,
                                          published=when, title=ex.title, source_document_id=cid))

    # 2. Site-authored FAQ entries.
    faq_questions = _faq_jsonld(soup, url)
    for d in soup.select("details > summary"):
        faq_questions.append(_clean(d.get_text(" ")))
    for dt in soup.select("dl dt"):
        faq_questions.append(_clean(dt.get_text(" ")))
    for h in soup.select("h2, h3, h4, .faq-question, [class*=faq] strong"):
        t = _clean(h.get_text(" "))
        if t.endswith("?"):
            faq_questions.append(t)
    for q in dict.fromkeys(faq_questions):
        if _ok(q) and q not in seen:
            seen.add(q)
            ex.records.append(ExtractedRecord(text=q, role="faq", method="html_faq", source_url=url,
                                              published=ex.published, updated=ex.modified, title=ex.title))

    # Links are collected before noise removal (navigation menus hold most of them).
    base_links = []
    for a in soup.find_all("a", href=True):
        c = absolute(a["href"], url)
        if not c or not same_site(c, url) or not is_crawlable_path(c):
            continue
        anchor = _clean(a.get_text(" "))[:120]
        rel = " ".join(a.get("rel") or []).lower()
        cls = " ".join(a.get("class") or []).lower()
        if "next" in rel or "next" in cls or (a.find_parent(class_=re.compile("pagination|nav-links", re.I))):
            base_links.append((c, "pagination", anchor))
        elif looks_relevant(c, anchor):
            base_links.append((c, "internal_link", anchor))
    ex.links = list(dict.fromkeys(base_links))[:max_links]

    # 3. Article summary: title + leading body text, kept as one record.
    for tag in soup.select(_NOISE):
        tag.decompose()
    for tag in soup.select("#comments, .comments-area, .sy-comments, .comment-list"):
        tag.decompose()
    main = soup.select_one("article") or soup.select_one("main") or soup.select_one("[role=main]") \
        or soup.select_one(".entry-content, .post-content, .article-body, .content")
    if main is not None:
        paras = [_clean(p.get_text(" ")) for p in main.find_all("p")]
        body = " ".join(p for p in paras if len(p) > 40)[:1500]
        if len(body) > 120:
            text = f"{ex.title}. {body}" if ex.title else body
            ex.records.append(ExtractedRecord(text=text[:MAX_RECORD_CHARS], role="article", method="html_article",
                                              source_url=url, published=ex.published, updated=ex.modified,
                                              title=ex.title))
    return ex


# ── Feeds and sitemaps ────────────────────────────────────────────────────

def extract_feed(content: str, url: str) -> Extraction:
    import feedparser
    feed = feedparser.parse(content)
    ex = Extraction(page_type="rss", title=_clean(feed.feed.get("title", "")) or None)
    for e in feed.entries:
        title = _clean(e.get("title", ""))
        summary = _clean(BeautifulSoup(e.get("summary", "") or "", "lxml").get_text(" "))
        raw_link = absolute(e.get("link") or "", url)
        link = canonicalize(raw_link) if raw_link else url
        text = (f"{title.rstrip('.')}. {summary}" if title and summary else title or summary)[:MAX_RECORD_CHARS]
        published = updated = None
        # dict.__contains__ checks real keys: feedparser otherwise aliases a missing
        # 'updated' to 'published', which would invent a modification date.
        if dict.__contains__(e, "published_parsed") and e["published_parsed"]:
            published = parse_date(datetime(*e["published_parsed"][:6], tzinfo=timezone.utc), "rss:published")
        if dict.__contains__(e, "updated_parsed") and e["updated_parsed"]:
            updated = parse_date(datetime(*e["updated_parsed"][:6], tzinfo=timezone.utc), "rss:updated")
        if _ok(text):
            ex.records.append(ExtractedRecord(text=text, role="news", method="rss", source_url=link,
                                              published=published, updated=updated, title=title,
                                              source_document_id=e.get("id")))
        if raw_link and canonicalize(raw_link) != canonicalize(url):
            ex.links.append((raw_link, "rss", title[:120]))
    return ex


def extract_sitemap(content: str, url: str, keywords_only: bool = True) -> Extraction:
    """Returns links from a sitemap or sitemap index (nested sitemaps are returned as links too)."""
    import xml.etree.ElementTree as ET
    ex = Extraction(page_type="sitemap")
    try:
        root = ET.fromstring(content.encode("utf-8") if isinstance(content, str) else content)
    except ET.ParseError:
        return ex
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    for loc in root.findall(".//sm:sitemap/sm:loc", ns):
        c = absolute(loc.text or "", url)
        if c:
            ex.links.append((c, "sitemap_index", ""))
    entries = []
    for node in root.findall(".//sm:url", ns):
        loc = node.find("sm:loc", ns)
        lastmod = node.find("sm:lastmod", ns)
        c = absolute(loc.text if loc is not None else "", url)
        if not c or not is_crawlable_path(c):
            continue
        if keywords_only and not looks_relevant(c):
            continue
        lm = parse_date(lastmod.text, "sitemap:lastmod") if lastmod is not None else None
        entries.append((lm.value if lm else datetime.min.replace(tzinfo=timezone.utc), c))
    # Most recently modified pages first.
    for _, c in sorted(entries, key=lambda t: t[0], reverse=True):
        ex.links.append((c, "sitemap", ""))
    return ex


# ── PDF ───────────────────────────────────────────────────────────────────

def extract_pdf(content: bytes, url: str, max_pages: int = 40) -> Extraction:
    from pypdf import PdfReader
    ex = Extraction(page_type="pdf")
    reader = PdfReader(io.BytesIO(content))
    info = reader.metadata or {}
    ex.title = _clean(str(info.get("/Title") or "")) or None
    ex.published = pdf_date(info.get("/CreationDate"), "pdf:CreationDate")
    ex.modified = pdf_date(info.get("/ModDate"), "pdf:ModDate")
    text = " ".join((p.extract_text() or "") for p in reader.pages[:max_pages])
    text = _clean(text)
    # FAQ-style PDFs: one record per question sentence.
    for q in re.findall(r"(?:(?<=\s)|^)(?:Q\.?\s*\d*[.:)]?\s*)?([A-Z][^?]{15,300}\?)", text):
        q = _clean(q)
        if _ok(q):
            ex.records.append(ExtractedRecord(text=q, role="faq", method="pdf_faq", source_url=url,
                                              published=ex.published, updated=ex.modified, title=ex.title))
    if not ex.records and len(text) > 120:
        ex.records.append(ExtractedRecord(text=text[:1500], role="article", method="pdf_text", source_url=url,
                                          published=ex.published, updated=ex.modified, title=ex.title))
    return ex


# ── Structured data (JSON / CSV) ──────────────────────────────────────────

def _dig(obj, path: Optional[str]):
    if not path:
        return obj
    for key in path.split("."):
        if isinstance(obj, dict):
            obj = obj.get(key)
        else:
            return None
    return obj


def records_from_rows(rows, url: str, cfg: dict, method: str) -> list:
    """Map tabular rows to records using cfg['field_map'] = {text, state, district, published_at, id}."""
    fm = {"text": "text", **(cfg.get("field_map") or {})}
    role = cfg.get("role", "query")
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        text = _clean(str(row.get(fm["text"]) or ""))
        if not _ok(text):
            continue
        pub = parse_date(row.get(fm["published_at"]), f"field:{fm['published_at']}") if fm.get("published_at") else None
        out.append(ExtractedRecord(
            text=text, role=role, method=method, source_url=url, published=pub,
            source_document_id=str(row.get(fm["id"])) if fm.get("id") and row.get(fm["id"]) is not None else None,
            state=_clean(str(row.get(fm["state"]))) if fm.get("state") and row.get(fm["state"]) else None,
            district=_clean(str(row.get(fm["district"]))) if fm.get("district") and row.get(fm["district"]) else None,
            metadata={k: row.get(v) for k, v in (cfg.get("metadata_fields") or {}).items()},
        ))
    return out


def extract_json(content: str, url: str, cfg: dict) -> Extraction:
    ex = Extraction(page_type="json")
    data = json.loads(content)
    rows = _dig(data, cfg.get("records_path"))
    if isinstance(rows, dict):
        rows = [rows]
    ex.records = records_from_rows(rows or [], url, cfg, "json_api")
    return ex


def extract_csv(content: str, url: str, cfg: dict) -> Extraction:
    ex = Extraction(page_type="csv")
    ex.records = records_from_rows(csv.DictReader(io.StringIO(content)), url, cfg, "csv")
    return ex
