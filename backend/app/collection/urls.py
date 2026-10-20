"""URL canonicalization and relevance helpers."""

import re
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

_TRACKING_PARAMS = re.compile(r"^(utm_[a-z]+|fbclid|gclid|mc_cid|mc_eid|ref|amp|_ga)$", re.IGNORECASE)
_DEFAULT_PORTS = {"http": 80, "https": 443}

SKIP_EXTENSIONS = (
    ".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp", ".woff", ".woff2",
    ".ttf", ".mp4", ".mp3", ".zip", ".rar", ".exe", ".apk", ".doc", ".docx", ".xls", ".xlsx", ".ppt",
)
SKIP_PATH_PARTS = (
    "/wp-admin", "/wp-includes", "/wp-json", "/login", "/signin", "/signup", "/register", "/cart",
    "/checkout", "/account", "/privacy", "/terms", "/disclaimer", "/cdn-cgi/", "/tag/", "/author/",
    "/feed", "/amp/", "/search", "/xmlrpc",
)

WELFARE_URL_KEYWORDS = (
    "scheme", "yojana", "yojna", "welfare", "subsidy", "beneficiar", "eligib", "pension", "kisan",
    "farmer", "pmay", "awas", "pmjay", "ayushman", "mgnrega", "nrega", "mudra", "svanidhi", "ujjwala",
    "kusum", "jan-dhan", "jandhan", "pmjdy", "fasal", "pmfby", "vishwakarma", "insurance", "bima",
    "faq", "grievance", "complaint", "apply", "status", "installment", "instalment",
)


def canonicalize(url: str, base: Optional[str] = None) -> Optional[str]:
    """Lowercase scheme/host, drop default port, fragment and tracking params,
    sort the query string, and remove the trailing slash (except for the root)."""
    if not url:
        return None
    url = url.strip()
    if base:
        url = urljoin(base, url)
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        return None
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        return None
    port = parts.port
    netloc = host if port in (None, _DEFAULT_PORTS.get(scheme)) else f"{host}:{port}"
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if len(path) > 1:
        path = path.rstrip("/")
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                             if not _TRACKING_PARAMS.match(k)))
    return urlunsplit((scheme, netloc, path, query, ""))


def absolute(url: str, base: Optional[str] = None) -> Optional[str]:
    """Absolute http(s) URL as published (fragment removed). Used for fetching;
    canonicalize() is used only to detect that two URLs are the same page."""
    if not url:
        return None
    try:
        parts = urlsplit(urljoin(base, url.strip()) if base else url.strip())
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        return None
    return urlunsplit((parts.scheme.lower(), parts.netloc, parts.path or "/", parts.query, ""))


def registrable_host(url: str) -> str:
    """Host without a leading 'www.' — used for same-site link filtering."""
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def same_site(a: str, b: str) -> bool:
    return registrable_host(a) == registrable_host(b)


def is_crawlable_path(url: str) -> bool:
    low = url.lower()
    path = urlsplit(low).path
    if path.endswith(SKIP_EXTENSIONS):
        return False
    return not any(p in path for p in SKIP_PATH_PARTS)


def looks_relevant(url: str, anchor_text: str = "") -> bool:
    hay = (url + " " + (anchor_text or "")).lower()
    return any(k in hay for k in WELFARE_URL_KEYWORDS)
