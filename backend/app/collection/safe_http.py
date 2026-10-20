"""
SSRF-safe HTTP fetching with politeness controls.

Every request (including every redirect hop) is checked by UrlPolicy:
  * scheme must be http/https, no credentials in the URL, port 80/443 only
  * hostname must not be localhost / *.local / *.internal
  * every resolved address must be a public (globally routable) IP
After the TCP connection is made, the actual peer address is checked again, which
defeats DNS-rebinding between our resolution and httpx's own.

Responses are streamed and cut off at max_bytes; only whitelisted content types
are accepted. Transient failures (timeouts, 408/425/429/5xx) are retried with
exponential backoff + jitter, honouring Retry-After (capped). Requests to the
same host are spaced by at least the host's crawl delay.
"""

import ipaddress
import logging
import random
import socket
import threading
import time
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from typing import Callable, Iterable, Optional
from urllib.parse import urljoin, urlsplit

import httpx

from backend.app.config import get_settings

logger = logging.getLogger(__name__)

REDIRECT_STATUSES = {301, 302, 303, 307, 308}
RETRY_STATUSES = {408, 425, 429, 500, 502, 503, 504}

DEFAULT_CONTENT_TYPES = (
    "text/html", "application/xhtml+xml", "application/xml", "text/xml", "application/rss+xml",
    "application/atom+xml", "application/json", "text/csv", "application/csv", "text/plain",
    "application/pdf",
)

_BLOCKED_HOST_SUFFIXES = (".local", ".localhost", ".internal", ".lan", ".home.arpa", ".intranet")


class FetchError(Exception):
    """A fetch that did not produce a usable response. `kind` is machine-readable."""

    def __init__(self, kind: str, message: str, url: str = "", status: Optional[int] = None):
        super().__init__(message)
        self.kind = kind  # unsafe_url / robots / http / timeout / network / tls / too_large / content_type / redirects
        self.url = url
        self.status = status


class UnsafeUrlError(FetchError):
    def __init__(self, message: str, url: str = ""):
        super().__init__("unsafe_url", message, url)


def _is_public_ip(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return addr.is_global and not addr.is_multicast and not addr.is_reserved


def default_resolver(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    return sorted({info[4][0] for info in infos})


@dataclass
class UrlPolicy:
    allowed_ports: tuple = (80, 443)
    resolver: Callable[[str], list] = default_resolver
    allow_private: bool = False  # only for explicitly isolated test setups

    def check(self, url: str) -> list[str]:
        """Validate a URL; returns the resolved IPs. Raises UnsafeUrlError."""
        try:
            parts = urlsplit(url)
        except ValueError:
            raise UnsafeUrlError("Malformed URL", url)
        if parts.scheme not in ("http", "https"):
            raise UnsafeUrlError(f"Scheme '{parts.scheme}' is not allowed", url)
        if parts.username or parts.password:
            raise UnsafeUrlError("Credentials in URLs are not allowed", url)
        host = (parts.hostname or "").lower().rstrip(".")
        if not host:
            raise UnsafeUrlError("URL has no host", url)
        try:
            port = parts.port or (443 if parts.scheme == "https" else 80)
        except ValueError:
            raise UnsafeUrlError("Invalid port", url)
        if port not in self.allowed_ports:
            raise UnsafeUrlError(f"Port {port} is not allowed", url)
        if host == "localhost" or host.endswith(_BLOCKED_HOST_SUFFIXES):
            raise UnsafeUrlError(f"Host '{host}' is not allowed", url)
        if self.allow_private:
            return []
        try:
            ipaddress.ip_address(host)
            ips = [host]
        except ValueError:
            try:
                ips = self.resolver(host)
            except (socket.gaierror, OSError) as e:
                raise FetchError("network", f"DNS resolution failed for {host}: {e}", url)
        if not ips:
            raise FetchError("network", f"No addresses for {host}", url)
        bad = [ip for ip in ips if not _is_public_ip(ip)]
        if bad:
            raise UnsafeUrlError(f"Host '{host}' resolves to non-public address {bad[0]}", url)
        return ips

    def check_peer(self, ip: Optional[str], url: str) -> None:
        if self.allow_private or not ip:
            return
        if not _is_public_ip(ip):
            raise UnsafeUrlError(f"Connected peer {ip} is not a public address", url)


class HostRateLimiter:
    """Per-host minimum spacing between requests (thread-safe)."""

    def __init__(self):
        self._next: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, host: str, delay: float) -> None:
        with self._lock:
            now = time.monotonic()
            at = max(now, self._next.get(host, 0.0))
            self._next[host] = at + max(delay, 0.0)
        sleep = at - time.monotonic()
        if sleep > 0:
            time.sleep(sleep)


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int
    headers: dict
    content: bytes
    content_type: str
    redirects: list = field(default_factory=list)
    elapsed: float = 0.0

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    @property
    def not_modified(self) -> bool:
        return self.status == 304

    @property
    def etag(self) -> Optional[str]:
        return self.headers.get("etag")

    @property
    def last_modified(self) -> Optional[str]:
        return self.headers.get("last-modified")

    def text(self) -> str:
        enc = None
        ctype = self.headers.get("content-type", "")
        if "charset=" in ctype:
            enc = ctype.split("charset=")[-1].split(";")[0].strip().strip('"')
        for candidate in (enc, "utf-8", "cp1252"):
            if not candidate:
                continue
            try:
                return self.content.decode(candidate)
            except (LookupError, UnicodeDecodeError):
                continue
        return self.content.decode("utf-8", errors="replace")


def _retry_after_seconds(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        try:
            return max(0.0, parsedate_to_datetime(value).timestamp() - time.time())
        except Exception:
            return None


class SafeFetcher:
    def __init__(self, policy: Optional[UrlPolicy] = None, transport: Optional[httpx.BaseTransport] = None,
                 rate_limiter: Optional[HostRateLimiter] = None, robots=None,
                 user_agent: Optional[str] = None, timeout: Optional[float] = None,
                 max_bytes: Optional[int] = None, max_retries: Optional[int] = None,
                 backoff_base: float = 1.0, max_redirects: int = 5, default_delay: Optional[float] = None,
                 sleep: Callable[[float], None] = time.sleep):
        s = get_settings()
        self.policy = policy or UrlPolicy()
        self.rate_limiter = rate_limiter or HostRateLimiter()
        self.robots = robots  # RobotsPolicy or None
        self.user_agent = user_agent or s.SCRAPER_USER_AGENT
        self.timeout = timeout or s.SCRAPER_DEFAULT_TIMEOUT
        self.max_bytes = max_bytes or s.SCRAPER_MAX_BYTES
        self.max_retries = s.SCRAPER_MAX_RETRIES if max_retries is None else max_retries
        self.backoff_base = backoff_base
        self.max_redirects = max_redirects
        self.default_delay = s.SCRAPER_DEFAULT_DELAY if default_delay is None else default_delay
        self._sleep = sleep
        self._client = httpx.Client(
            timeout=httpx.Timeout(self.timeout, connect=min(10.0, self.timeout)),
            follow_redirects=False,  # redirects are validated hop by hop below
            trust_env=False,         # never route through env-configured proxies
            transport=transport,
            headers={"User-Agent": self.user_agent,
                     "Accept-Language": "en-IN,en;q=0.9,hi;q=0.8"},
        )

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def fetch(self, url: str, *, accept: Iterable[str] = DEFAULT_CONTENT_TYPES, delay: Optional[float] = None,
              etag: Optional[str] = None, last_modified: Optional[str] = None,
              check_robots: bool = True, max_bytes: Optional[int] = None) -> FetchResult:
        attempt = 0
        while True:
            try:
                return self._fetch_once(url, accept=tuple(accept), delay=delay, etag=etag,
                                        last_modified=last_modified, check_robots=check_robots,
                                        max_bytes=max_bytes or self.max_bytes)
            except _Retryable as r:
                attempt += 1
                if attempt > self.max_retries:
                    raise FetchError(r.kind, f"{r.message} (gave up after {attempt} attempts)", url, r.status)
                wait = self.backoff_base * (2 ** (attempt - 1)) + random.uniform(0, self.backoff_base / 2)
                if r.retry_after is not None:
                    wait = max(wait, min(r.retry_after, 60.0))
                logger.info("Retrying %s in %.1fs (%s)", url, wait, r.message)
                self._sleep(wait)

    def _fetch_once(self, url, *, accept, delay, etag, last_modified, check_robots, max_bytes) -> FetchResult:
        current = url
        redirects: list[str] = []
        started = time.monotonic()
        for _ in range(self.max_redirects + 1):
            self.policy.check(current)
            host = (urlsplit(current).hostname or "").lower()
            crawl_delay = self.default_delay if delay is None else delay
            if check_robots and self.robots is not None:
                decision = self.robots.check(current, self)
                if not decision.allowed:
                    msg = (f"Not fetched: {decision.reason}; treated as disallow-all (RFC 9309)"
                           if decision.reason.startswith("robots.txt unreachable") else "Disallowed by robots.txt")
                    raise FetchError("robots", msg, current)
                if decision.crawl_delay:
                    crawl_delay = max(crawl_delay, decision.crawl_delay)
            self.rate_limiter.wait(host, crawl_delay)

            headers = {"Accept": ", ".join(accept) + ", */*;q=0.1"}
            if etag:
                headers["If-None-Match"] = etag
            if last_modified:
                headers["If-Modified-Since"] = last_modified
            try:
                with self._client.stream("GET", current, headers=headers) as resp:
                    stream = resp.extensions.get("network_stream")
                    peer = None
                    if stream is not None:
                        addr = stream.get_extra_info("server_addr")
                        peer = addr[0] if addr else None
                    self.policy.check_peer(peer, current)

                    status = resp.status_code
                    if status in REDIRECT_STATUSES:
                        location = resp.headers.get("location")
                        if not location:
                            raise FetchError("http", f"Redirect {status} without Location", current, status)
                        redirects.append(current)
                        current = urljoin(current, location)
                        continue
                    if status in RETRY_STATUSES:
                        raise _Retryable("http", f"HTTP {status}", status,
                                         _retry_after_seconds(resp.headers.get("retry-after")))
                    hdrs = {k.lower(): v for k, v in resp.headers.items()}
                    ctype = hdrs.get("content-type", "").split(";")[0].strip().lower()
                    if status == 304 or status >= 400:
                        return FetchResult(url, current, status, hdrs, b"", ctype, redirects,
                                           time.monotonic() - started)
                    if ctype and not any(ctype == a or ctype.startswith(a) for a in accept):
                        raise FetchError("content_type", f"Content-Type '{ctype}' not accepted", current, status)
                    declared = hdrs.get("content-length")
                    if declared and declared.isdigit() and int(declared) > max_bytes:
                        raise FetchError("too_large", f"Response of {declared} bytes exceeds {max_bytes}", current, status)
                    buf = bytearray()
                    for chunk in resp.iter_bytes():
                        buf.extend(chunk)
                        if len(buf) > max_bytes:
                            raise FetchError("too_large", f"Response exceeds {max_bytes} bytes", current, status)
                    return FetchResult(url, current, status, hdrs, bytes(buf), ctype, redirects,
                                       time.monotonic() - started)
            except (httpx.TimeoutException,) as e:
                raise _Retryable("timeout", f"Timeout: {type(e).__name__}")
            except httpx.ConnectError as e:
                msg = str(e)
                if "CERTIFICATE_VERIFY_FAILED" in msg or "SSL" in msg:
                    raise FetchError("tls", f"TLS verification failed: {msg[:160]}", current)
                raise _Retryable("network", f"Connection failed: {msg[:160]}")
            except (httpx.RemoteProtocolError, httpx.ReadError) as e:
                raise _Retryable("network", f"{type(e).__name__}: {str(e)[:160]}")
            except httpx.HTTPError as e:
                raise FetchError("network", f"{type(e).__name__}: {str(e)[:160]}", current)
        raise FetchError("redirects", f"More than {self.max_redirects} redirects", url)


class _Retryable(Exception):
    def __init__(self, kind: str, message: str, status: Optional[int] = None, retry_after: Optional[float] = None):
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.status = status
        self.retry_after = retry_after
