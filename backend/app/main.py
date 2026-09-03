"""ResearchMind AI — FastAPI application entrypoint."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    auth,
    documents,
    graph,
    knowledge,
    monitoring,
    monitors,
    notifications,
    research,
    schedules,
    system,
)
from app.config import get_settings
from app.database import init_db
from app.security.middleware import RateLimitMiddleware, SecurityHeadersMiddleware
from app.services.scheduler import scheduler

settings = get_settings()


def _apply_ca_bundle() -> None:
    """Trust a corporate/self-signed CA for outbound HTTPS.

    On a TLS-inspecting network (e.g. a Sophos proxy), httpx/requests use their own
    certifi bundle and reject the proxy's re-signed certs. Exporting SSL_CERT_FILE /
    REQUESTS_CA_BUNDLE (which httpx honours via trust_env) before any client is built
    makes every outbound fetch verify against the provided bundle. No-op if unset.
    """
    if not settings.ca_bundle:
        return
    path = Path(settings.ca_bundle)
    if not path.is_absolute():
        path = (Path(__file__).resolve().parent.parent / settings.ca_bundle).resolve()
    if not path.exists():
        print(f"[ca_bundle] configured path not found, ignoring: {path}")
        return
    os.environ.setdefault("SSL_CERT_FILE", str(path))
    os.environ.setdefault("REQUESTS_CA_BUNDLE", str(path))
    print(f"[ca_bundle] trusting corporate CA bundle: {path}")


_apply_ca_bundle()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    scheduler.start()  # in-process poller for scheduled research
    try:
        yield
    finally:
        await scheduler.stop()


app = FastAPI(
    title="ResearchMind AI",
    version="0.1.0",
    description="Personal Autonomous Research & R&D AI Agent",
    lifespan=lifespan,
)

# Middleware runs bottom-up: rate limit first, then security headers, then CORS.
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware, limit_per_minute=settings.rate_limit_per_minute)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(system.router)
app.include_router(auth.router)
app.include_router(research.router)
app.include_router(monitors.router)  # /research/{id}/monitor (#6)
app.include_router(documents.router)
app.include_router(knowledge.router)
app.include_router(graph.router)  # /knowledge/entities* — Knowledge Graph (#7)
app.include_router(monitoring.router)
app.include_router(schedules.router)
app.include_router(notifications.router)


@app.get("/")
async def root():
    return {"name": "ResearchMind AI", "docs": "/docs", "health": "/health"}
