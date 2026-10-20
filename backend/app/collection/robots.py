"""
robots.txt policy (RFC 9309 semantics), cached per origin.

  2xx         → parse and obey (Disallow / Allow / Crawl-delay for our agent or *)
  4xx         → no restrictions ("unavailable" per RFC 9309 §2.3.1.3)
  5xx / error → disallow everything for this run ("unreachable", §2.3.1.4)
"""

import threading
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from backend.app.collection.safe_http import FetchError


@dataclass
class RobotsDecision:
    allowed: bool
    reason: str
    crawl_delay: Optional[float] = None
    sitemaps: tuple = ()


class RobotsPolicy:
    def __init__(self, user_agent: str, ttl_seconds: int = 6 * 3600):
        self.agent_token = user_agent.split("/")[0]
        self.ttl = ttl_seconds
        self._cache: dict[str, tuple[float, Optional[RobotFileParser], str]] = {}
        self._lock = threading.Lock()

    def _origin(self, url: str) -> str:
        p = urlsplit(url)
        return f"{p.scheme}://{p.netloc}"

    def _load(self, origin: str, fetcher) -> tuple[Optional[RobotFileParser], str]:
        with self._lock:
            hit = self._cache.get(origin)
            if hit and time.time() - hit[0] < self.ttl:
                return hit[1], hit[2]
        robots_url = origin + "/robots.txt"
        try:
            res = fetcher.fetch(robots_url, accept=("text/plain", "text/html", "application/octet-stream"),
                                check_robots=False, max_bytes=512 * 1024, delay=0)
            if res.ok:
                rp = RobotFileParser()
                rp.parse(res.text().splitlines())
                parsed, state = rp, "parsed"
            elif 400 <= res.status < 500:
                parsed, state = None, f"no robots.txt (HTTP {res.status})"
            else:
                parsed, state = False, f"robots.txt unreachable (HTTP {res.status})"
        except FetchError as e:
            parsed, state = False, f"robots.txt unreachable ({e.kind})"
        with self._lock:
            self._cache[origin] = (time.time(), parsed, state)
        return parsed, state

    def check(self, url: str, fetcher) -> RobotsDecision:
        parsed, state = self._load(self._origin(url), fetcher)
        if parsed is False:
            return RobotsDecision(False, state)
        if parsed is None:
            return RobotsDecision(True, state)
        allowed = parsed.can_fetch(self.agent_token, url)
        delay = parsed.crawl_delay(self.agent_token)
        sitemaps = tuple(parsed.site_maps() or ())
        return RobotsDecision(allowed, "allowed by robots.txt" if allowed else "disallowed by robots.txt",
                              float(delay) if delay else None, sitemaps)
