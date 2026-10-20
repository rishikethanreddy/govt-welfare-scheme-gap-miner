"""
Access control and request limits.

Authentication model: a single operator API key (ADMIN_API_KEY) sent in the
X-API-Key header. It protects every write, collection, processing and admin
endpoint. Read-only analytics are public. There is no default key — when the
variable is unset, protected endpoints return 503 instead of being open.
The frontend never embeds the key; the operator types it into the UI, which
keeps it in sessionStorage for the browser session only.
"""

import hmac
import logging
import threading
import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException, Request, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from backend.app.config import get_settings

logger = logging.getLogger(__name__)


class SlidingWindowLimiter:
    def __init__(self):
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window: float = 60.0) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > window:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True

    def reset(self):
        with self._lock:
            self._hits.clear()


limiter = SlidingWindowLimiter()


def client_id(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def rate_limited(request: Request) -> None:
    limit = get_settings().RATE_LIMIT_PER_MINUTE
    if not limiter.allow(f"{client_id(request)}:{request.url.path}", limit):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many requests; please slow down.")


def require_admin(request: Request, _: None = Depends(rate_limited)) -> str:
    expected = get_settings().ADMIN_API_KEY
    if not expected:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Administrative actions are disabled: ADMIN_API_KEY is not configured on the server.")
    supplied = request.headers.get("x-api-key", "")
    if not supplied or not hmac.compare_digest(supplied.encode(), expected.encode()):
        logger.warning("Rejected admin request %s %s from %s", request.method, request.url.path, client_id(request))
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "A valid X-API-Key header is required for this action.",
                            headers={"WWW-Authenticate": "ApiKey"})
    return "admin"


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Rejects requests whose declared body exceeds the limit before reading it.
    Uploads are additionally size-checked while reading (see datasets router)."""

    async def dispatch(self, request, call_next):
        s = get_settings()
        limit = (s.MAX_UPLOAD_SIZE_MB * 1024 * 1024 + 64 * 1024) if request.url.path.startswith("/api/datasets") \
            else 1024 * 1024
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > limit:
            return JSONResponse({"detail": f"Request body exceeds {limit // (1024 * 1024)} MB limit."}, status_code=413)
        return await call_next(request)
