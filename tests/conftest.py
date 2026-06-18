"""
Shared pytest fixtures for nexus-booking test suite.

Uses an in-memory SQLite database (via aiosqlite) so tests are
fully isolated and require no external PostgreSQL instance.

Fixture hierarchy:
  settings      — isolated test Settings (SQLite URL)
  app           — fresh FastAPI app per test (factory-injected settings)
  client        — async httpx.AsyncClient against the test app
  admin_token   — HMAC JWT for admin role
  user_token    — HMAC JWT for user role
  sample_booking — a pre-created booking in the test DB
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth import generate_token
from app.config import Settings
from app.database import Base, get_db_dep
from app.main import create_app
from app.services.availability import AvailabilityIndex, get_availability_index

# ── Test database ──────────────────────────────────────────────────────────────

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(autouse=True)
async def reset_availability_index(request):
    """Reset the global availability index singleton before each test.
    Prevents state leakage between tests that create different apps.
    Skipped for BDD tests which manage their own index via bdd_client fixture."""
    # BDD tests use the bdd_client fixture which manages the index directly
    if "bdd_client" in request.fixturenames:
        yield
        return
    import app.services.availability as av_module
    av_module._index = None
    yield
    av_module._index = None


@pytest.fixture(scope="function")
def test_settings() -> Settings:
    """Isolated settings pointing to in-memory SQLite."""
    return Settings(
        database_url=TEST_DB_URL,
        jwt_secret="test-secret-key",
        email_enabled=False,
        debug=True,
        # Large window so far-future test dates (e.g. 2099-xx-xx) are covered
        availability_window_days=50000,
    )


@pytest_asyncio.fixture(scope="function")
async def test_engine(test_settings):
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def test_session(test_engine):
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest_asyncio.fixture(scope="function")
async def fresh_index():
    """A clean AvailabilityIndex for each test."""
    idx = AvailabilityIndex()
    await idx.build({})
    return idx


@pytest_asyncio.fixture(scope="function")
async def client(test_settings, test_engine):
    """
    httpx.AsyncClient wired to a fresh FastAPI app with test DB.
    Overrides the DB dependency to use the test engine.

    Note: ASGITransport does NOT trigger ASGI lifespan events, so we
    manually build the availability index here using test_settings.
    """
    import app.services.availability as av_module

    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    async def override_db():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    # Build a fresh availability index with the test window
    idx = av_module.AvailabilityIndex()
    await idx.build({}, window_days=test_settings.availability_window_days)
    av_module._index = idx

    app_instance = create_app(test_settings)
    app_instance.dependency_overrides[get_db_dep] = override_db

    # Patch auth to use test JWT secret (get_settings() is lru_cached globally)
    import unittest.mock as mock
    import app.auth as auth_module
    auth_module._original_get_settings = auth_module.get_settings
    auth_module.get_settings = mock.MagicMock(return_value=test_settings)

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app_instance),
            base_url="http://test",
        ) as ac:
            yield ac
    finally:
        # Restore auth get_settings
        import app.auth as auth_module
        if hasattr(auth_module, "_original_get_settings"):
            auth_module.get_settings = auth_module._original_get_settings
            del auth_module._original_get_settings


# ── Auth tokens ────────────────────────────────────────────────────────────────

@pytest.fixture
def admin_token(test_settings) -> str:
    return generate_token(
        {"sub": "admin-user-id", "role": "admin", "username": "admin"},
        secret=test_settings.jwt_secret,
    )


@pytest.fixture
def user_token(test_settings) -> str:
    return generate_token(
        {"sub": "regular-user-id", "role": "user", "username": "testuser"},
        secret=test_settings.jwt_secret,
    )


@pytest.fixture
def admin_headers(admin_token) -> dict:
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture
def user_headers(user_token) -> dict:
    return {"Authorization": f"Bearer {user_token}"}


# ── Sample booking payload ─────────────────────────────────────────────────────

@pytest.fixture
def booking_payload() -> dict:
    """Valid booking creation payload."""
    return {
        "name": "Jane Doe",
        "email": "jane@example.com",
        "company": "Acme Corp",
        "meetingType": "discovery",
        "details": "Looking to discuss microservices architecture for our platform.",
        "date": "2099-06-15",   # far future — always available
        "time": "09:00",
    }
