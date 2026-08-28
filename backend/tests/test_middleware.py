"""Middleware tested in isolation on a minimal app (independent of global config)."""
import httpx
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from app.security.middleware import RateLimitMiddleware, SecurityHeadersMiddleware


def _app(limit: int) -> Starlette:
    async def ok(request):
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/", ok), Route("/thing/stream", ok)])
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RateLimitMiddleware, limit_per_minute=limit)
    return app


async def test_security_headers_present():
    transport = httpx.ASGITransport(app=_app(0))
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/")
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["x-frame-options"] == "DENY"
        assert r.headers["referrer-policy"] == "no-referrer"


async def test_rate_limit_blocks_after_threshold():
    transport = httpx.ASGITransport(app=_app(3))
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        codes = [(await c.get("/")).status_code for _ in range(5)]
        assert codes == [200, 200, 200, 429, 429]
        blocked = await c.get("/")
        assert "retry-after" in {k.lower() for k in blocked.headers}


async def test_rate_limit_exempts_stream_endpoints():
    transport = httpx.ASGITransport(app=_app(2))
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        codes = [(await c.get("/thing/stream")).status_code for _ in range(5)]
        assert all(code == 200 for code in codes)


async def test_rate_limit_disabled_when_zero():
    transport = httpx.ASGITransport(app=_app(0))
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        codes = [(await c.get("/")).status_code for _ in range(10)]
        assert all(code == 200 for code in codes)
