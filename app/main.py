"""
nexus-booking — FastAPI application factory.

Architecture:
  - Factory pattern: create_app(settings=None) → FastAPI
    Inject custom Settings in tests for full isolation.
  - Lifespan context: DB pool init → availability index build → shutdown cleanup
  - CORS: configurable via settings.cors_origins
  - Standard endpoints: /health, /info, /docs (OpenAPI)
  - Versioned routes under /v1/

Complexity:
  Startup: O(n) where n = existing bookings (index build)
  Request: O(1) per booking lookup, O(d) per availability range query
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import Optional

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.config import Settings, get_settings
from app.database import create_tables, dispose_engine, get_db
from app.models import BookingModel, HealthResponse, InfoResponse
from app.routers.availability import router as availability_router
from app.routers.bookings import router as bookings_router
from app.services.availability import get_availability_index

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ]
)
logger = structlog.get_logger("nexus-booking")

_start_time = time.monotonic()


def _make_lifespan(settings: Settings):
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("Starting nexus-booking", port=settings.port, debug=settings.debug)

        # 1. Ensure tables exist (dev/test — production uses Alembic)
        await create_tables()

        # 2. Build availability index: O(n) scan of existing bookings
        idx = get_availability_index()
        booked_map: dict[str, set[str]] = defaultdict(set)
        async with get_db() as db:
            result = await db.execute(
                select(BookingModel.date, BookingModel.time).where(
                    BookingModel.cancelled == False  # noqa: E712
                )
            )
            for row in result.all():
                booked_map[row.date].add(row.time)

        await idx.build(dict(booked_map), window_days=cfg.availability_window_days)
        logger.info("Availability index built", window_days=cfg.availability_window_days)

        yield

        # Shutdown: dispose DB connection pool
        await dispose_engine()
        logger.info("nexus-booking shut down cleanly")

    return lifespan


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    """
    Application factory.

    Pass custom Settings for tests:
        app = create_app(Settings(database_url="sqlite+aiosqlite:///:memory:"))
    """
    cfg = settings or get_settings()

    app = FastAPI(
        title="nexus-booking",
        version=cfg.version,
        description=(
            "Standalone appointment booking microservice for NexusConsult. "
            "Provides async booking CRUD, availability management, "
            "and email notifications. Part of the NexusConsult portfolio."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=_make_lifespan(cfg),
    )

    # ── CORS ──────────────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Standard endpoints ────────────────────────────────────────────────────
    @app.get("/health", response_model=HealthResponse, tags=["meta"])
    async def health():
        """Liveness probe — k8s / gateway health check."""
        return HealthResponse(
            status="ok",
            service=cfg.app_name,
            version=cfg.version,
            uptime_seconds=round(time.monotonic() - _start_time, 2),
        )

    @app.get("/info", response_model=InfoResponse, tags=["meta"])
    async def info():
        """Service metadata — consumed by the main portfolio gateway."""
        return InfoResponse(
            name=cfg.app_name,
            version=cfg.version,
            port=cfg.port,
            description="Appointment booking service with async availability index",
            endpoints=[
                {"method": "GET",    "path": "/health",             "auth": False, "description": "Health check"},
                {"method": "GET",    "path": "/info",               "auth": False, "description": "Service metadata"},
                {"method": "GET",    "path": "/v1/bookings",        "auth": True,  "description": "List all bookings (admin)"},
                {"method": "POST",   "path": "/v1/bookings",        "auth": False, "description": "Create a booking"},
                {"method": "GET",    "path": "/v1/bookings/{id}",   "auth": False, "description": "Get booking by ID"},
                {"method": "PATCH",  "path": "/v1/bookings/{id}",   "auth": True,  "description": "Update booking (admin)"},
                {"method": "DELETE", "path": "/v1/bookings/{id}",   "auth": True,  "description": "Delete booking (admin)"},
                {"method": "GET",    "path": "/v1/availability",    "auth": False, "description": "Available slots by date range"},
            ],
        )

    # ── Routers ───────────────────────────────────────────────────────────────
    app.include_router(bookings_router)
    app.include_router(availability_router)

    # ── Global error handler ──────────────────────────────────────────────────
    @app.exception_handler(Exception)
    async def global_exc_handler(request: Request, exc: Exception):
        import uuid
        logger.error("Unhandled exception", path=str(request.url), error=str(exc))
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal server error",
                "code": "INTERNAL_ERROR",
                "details": {},
                "request_id": str(uuid.uuid4()),
            },
        )

    return app


# Module-level instance for uvicorn / gunicorn
app = create_app()
