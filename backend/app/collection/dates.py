"""
Publication / modification date extraction.

Only dates that the source itself states are returned. If nothing trustworthy
is found the result is None — the crawl time is never used as a substitute.
Timestamps without an explicit offset are interpreted as India Standard Time
(all registered sources are Indian) and the assumption is recorded.
"""

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

IST = timezone(timedelta(hours=5, minutes=30))
_MIN_DATE = datetime(1990, 1, 1, tzinfo=timezone.utc)


@dataclass
class DateInfo:
    value: datetime
    source: str  # e.g. "meta:article:published_time", "jsonld:datePublished", "rss:published"


def parse_date(raw, source: str) -> Optional[DateInfo]:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        dt = raw
    else:
        text = str(raw).strip()
        if not text or len(text) > 64:
            return None
        try:
            from dateutil import parser as du
            dt = du.parse(text, fuzzy=False)
        except (ValueError, OverflowError, TypeError):
            return None
    note = source
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
        note = f"{source} (no offset; IST assumed)"
    dt = dt.astimezone(timezone.utc)
    if dt < _MIN_DATE or dt > datetime.now(timezone.utc) + timedelta(days=1):
        return None  # implausible: reject rather than store a wrong date
    return DateInfo(dt, note)


_META_PUBLISHED = (
    "article:published_time", "og:published_time", "datepublished", "publishdate", "pubdate",
    "publish-date", "dc.date.issued", "dcterms.created", "dc.date", "date", "sailthru.date",
)
_META_MODIFIED = ("article:modified_time", "og:updated_time", "datemodified", "dcterms.modified", "last-modified")


def _jsonld_dates(soup) -> tuple[Optional[str], Optional[str]]:
    pub = mod = None
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
                t = node.get("@type")
                types = t if isinstance(t, list) else [t]
                if any(x in ("Article", "NewsArticle", "BlogPosting", "WebPage", "Report", "FAQPage") for x in types):
                    pub = pub or node.get("datePublished")
                    mod = mod or node.get("dateModified")
                stack.extend(v for v in node.values() if isinstance(v, (dict, list)))
    return pub, mod


def html_dates(soup) -> tuple[Optional[DateInfo], Optional[DateInfo]]:
    """(published, modified) from structured page metadata, in priority order."""
    pub_raw, mod_raw = _jsonld_dates(soup)
    published = parse_date(pub_raw, "jsonld:datePublished") if pub_raw else None
    modified = parse_date(mod_raw, "jsonld:dateModified") if mod_raw else None
    metas = {}
    for m in soup.find_all("meta"):
        key = (m.get("property") or m.get("name") or m.get("itemprop") or "").strip().lower()
        if key and m.get("content") and key not in metas:
            metas[key] = m["content"]
    if not published:
        for k in _META_PUBLISHED:
            if k in metas and (published := parse_date(metas[k], f"meta:{k}")):
                break
    if not modified:
        for k in _META_MODIFIED:
            if k in metas and (modified := parse_date(metas[k], f"meta:{k}")):
                break
    if not published:
        t = soup.find("time", attrs={"itemprop": re.compile("datePublished", re.I)}) or \
            soup.find("time", class_=re.compile(r"(publish|entry-date|post-date)", re.I))
        if t and t.get("datetime"):
            published = parse_date(t["datetime"], "time[datetime]")
    return published, modified


def pdf_date(raw: Optional[str], source: str) -> Optional[DateInfo]:
    """PDF dates look like D:20240115103000+05'30'."""
    if not raw:
        return None
    m = re.match(r"D:(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?([+\-Z])?(\d{2})?'?(\d{2})?", str(raw))
    if not m:
        return None
    y, mo, d, h, mi, s, sign, oh, om = m.groups()
    try:
        dt = datetime(int(y), int(mo or 1), int(d or 1), int(h or 0), int(mi or 0), int(s or 0))
    except ValueError:
        return None
    if sign in ("+", "-") and oh:
        off = timedelta(hours=int(oh), minutes=int(om or 0))
        dt = dt.replace(tzinfo=timezone(off if sign == "+" else -off))
    elif sign == "Z":
        dt = dt.replace(tzinfo=timezone.utc)
    return parse_date(dt, source)
