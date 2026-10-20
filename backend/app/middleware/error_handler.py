"""
Error handling and request logging middleware.

Unhandled exceptions return a generic message with a request id; details go to
the server log only. Request logs contain method, path, status and duration —
never query strings (they may carry search text) or bodies.
"""

import logging
import time
import uuid
from datetime import datetime, timezone

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


class ErrorHandlerMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = uuid.uuid4().hex[:8]
        request.state.request_id = request_id
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response
        except Exception as exc:
            logger.error("Unhandled error [request_id=%s] %s %s: %s", request_id, request.method,
                         request.url.path, type(exc).__name__, exc_info=True)
            return JSONResponse(status_code=500, content={
                "error_code": "INTERNAL_ERROR",
                "detail": "An unexpected error occurred. The error has been logged.",
                "request_id": request_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        if request.url.path.startswith("/api") and not request.url.path.endswith("/stream"):
            logger.info("%s %s → %s (%.3fs)", request.method, request.url.path, response.status_code,
                        time.perf_counter() - start)
        return response
