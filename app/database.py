"""
Async database layer using SQLAlchemy 2.x async engine + asyncpg driver.

Connection pool: min_size=2, max_size=10 (tuned for low-concurrency microservice).
All queries use async sessions — no blocking I/O on the event loop.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

# Module-level engine — shared across all requests (connection pool)
_engine = None
_session_factory = None


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""
    pass


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            pool_size=2,
            max_overflow=8,
            pool_pre_ping=True,   # Detect stale connections
            echo=settings.debug,
        )
    return _engine


def get_session_factory():
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _session_factory


@asynccontextmanager
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Async context manager for a database session.

    Usage:
        async with get_db() as db:
            result = await db.execute(select(Booking))
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_db_dep() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a database session."""
    async with get_db() as session:
        yield session


async def create_tables() -> None:
    """Create all tables if they don't exist (dev/test convenience)."""
    from app.models import BookingModel  # noqa: F401 — registers the model
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose_engine() -> None:
    """Dispose connection pool on shutdown."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
