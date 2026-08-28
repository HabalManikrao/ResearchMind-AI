"""Rate limiting and security-header middleware (spec §21)."""
from __future__ import annotations

import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "X-XSS-Protection": "0",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        for k, v in _SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window per-client-IP limiter. In-process (lean-local); swap for a
    Redis-backed limiter when scaling out."""

    def __init__(self, app, *, limit_per_minute: int) -> None:
        super().__init__(app)
        self.limit = limit_per_minute
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next):
        if self.limit <= 0 or request.method == "OPTIONS":
            return await call_next(request)
        # SSE streams are long-lived; don't count them against the limit.
        if request.url.path.endswith("/stream"):
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        now = time.monotonic()
        window = self._hits[client_ip]
        cutoff = now - 60.0
        while window and window[0] < cutoff:
            window.popleft()
        if len(window) >= self.limit:
            retry = max(1, int(60 - (now - window[0])))
            return JSONResponse(
                {"detail": "Rate limit exceeded. Slow down."},
                status_code=429,
                headers={"Retry-After": str(retry)},
            )
        window.append(now)
        return await call_next(request)
