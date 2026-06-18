# nexus-booking

> Standalone async appointment booking microservice — part of the NexusConsult portfolio.

[![CI](https://github.com/itkdaniel/nexus-booking/actions/workflows/ci.yml/badge.svg)](https://github.com/itkdaniel/nexus-booking/actions/workflows/ci.yml)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688.svg)](https://fastapi.tiangolo.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Overview

`nexus-booking` is a production-grade FastAPI microservice that manages consultation
bookings for the NexusConsult platform. It provides:

- **Full booking CRUD** — create, read, update, cancel, delete
- **Availability index** — in-memory O(1) slot management built at startup in O(n)
- **HMAC-SHA256 JWT auth** — role-based access control (admin / user)
- **Async email** — `aiosmtplib` with fire-and-forget background dispatch
- **Comprehensive tests** — unit, BDD (pytest-bdd), property (Hypothesis), regression, E2E

---

## Quick Start

```bash
# 1. Clone
git clone https://github.com/itkdaniel/nexus-booking.git
cd nexus-booking

# 2. Install
pip install -r requirements-dev.txt

# 3. Configure
cp .env.example .env
# Edit DATABASE_URL, JWT_SECRET, etc.

# 4. Run (dev)
uvicorn app.main:app --reload --port 8002

# 5. Open docs
open http://localhost:8002/docs
```

### Docker Compose

```bash
# Start Postgres + booking service
docker compose up --build

# Run tests in Docker
docker compose -f docker-compose.test.yml up --build --abort-on-container-exit
```

---

## API Reference

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/health` | — | Liveness probe |
| `GET` | `/info` | — | Service metadata |
| `GET` | `/docs` | — | Swagger UI |
| `GET` | `/v1/bookings` | admin | List all bookings |
| `POST` | `/v1/bookings` | — | Create booking |
| `GET` | `/v1/bookings/{id}` | — | Get booking by ID |
| `PATCH` | `/v1/bookings/{id}` | admin | Update / cancel booking |
| `DELETE` | `/v1/bookings/{id}` | admin | Hard delete booking |
| `GET` | `/v1/availability?start=…&end=…` | — | Available slots by range |

### Create Booking

```bash
curl -X POST http://localhost:8002/v1/bookings \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Jane Doe",
    "email": "jane@example.com",
    "company": "Acme Corp",
    "meetingType": "discovery",
    "details": "Need help with microservices decomposition.",
    "date": "2025-06-15",
    "time": "09:00"
  }'
```

### Get Availability

```bash
curl "http://localhost:8002/v1/availability?start=2025-06-15&end=2025-06-21"
# Returns: {"2025-06-15": ["09:00", "09:15", ...], "2025-06-16": [...]}
```

### Admin: Cancel a Booking

```bash
curl -X PATCH http://localhost:8002/v1/bookings/<id> \
  -H "Authorization: Bearer <admin-jwt>" \
  -H "Content-Type: application/json" \
  -d '{"cancelled": true, "cancelReason": "Client request"}'
```

---

## Architecture

```
nexus-booking/
├── app/
│   ├── main.py            # create_app() factory + lifespan
│   ├── config.py          # pydantic-settings (env-driven)
│   ├── database.py        # SQLAlchemy 2.x async engine + session factory
│   ├── models.py          # ORM model + Pydantic schemas
│   ├── auth.py            # HMAC-SHA256 JWT (require_auth / require_admin)
│   ├── routers/
│   │   ├── bookings.py    # CRUD endpoints
│   │   └── availability.py # Slot query endpoint
│   └── services/
│       ├── availability.py # In-memory O(1) slot index
│       └── email.py       # aiosmtplib async email service
├── tests/
│   ├── conftest.py        # Shared fixtures (SQLite in-memory)
│   ├── unit/              # Pure unit tests (no I/O)
│   ├── bdd/               # pytest-bdd with .feature files
│   ├── property/          # Hypothesis property tests (DDT)
│   ├── regression/        # API contract stability tests
│   └── e2e/               # Full lifecycle tests
├── alembic/               # Database migrations
├── .github/workflows/     # CI/CD (lint, unit, bdd, property, regression, e2e, docker)
├── Dockerfile             # Multi-stage production build
└── docker-compose.yml     # Local dev with Postgres
```

### Key Design Decisions

**Factory Pattern** — `create_app(settings=None)` enables dependency injection in tests:
```python
app = create_app(Settings(database_url="sqlite+aiosqlite:///:memory:"))
```

**Availability Index** — Built O(n) at startup from DB, then O(1) per slot read/write:
```python
idx = get_availability_index()
slots = idx.get_slots("2025-06-15")  # O(1)
await idx.mark_booked("2025-06-15", "09:00")  # O(1)
```

**Async everywhere** — `asyncio.gather()` for concurrent email dispatch, `anyio` for CPU-bound work:
```python
await asyncio.gather(send_to_user(...), send_to_admin(...))
```

**Error envelope** — All endpoints return consistent `{"error", "code", "details", "request_id"}`.

---

## Configuration

All settings are read from environment variables (or `.env`). See `.env.example`.

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://...` | Async SQLAlchemy URL |
| `JWT_SECRET` | `change-me` | HMAC signing key (must match portfolio) |
| `PORT` | `8002` | Service port |
| `EMAIL_ENABLED` | `false` | Enable SMTP email dispatch |
| `SMTP_HOST` | `""` | SMTP server hostname |
| `AVAILABILITY_WINDOW_DAYS` | `30` | Days ahead to pre-build slot index |
| `CORS_ORIGINS` | `["*"]` | JSON list of allowed origins |

---

## Testing

```bash
# All tests
pytest

# By category
pytest -m unit
pytest -m bdd
pytest -m property
pytest -m regression
pytest -m e2e

# With coverage
pytest --cov=app --cov-report=html
open htmlcov/index.html
```

### Test Stats

| Category | Tests | Description |
|----------|-------|-------------|
| Unit | ~35 | Pure logic, no I/O |
| BDD | ~15 | Gherkin scenarios (pytest-bdd) |
| Property | ~10 | Hypothesis (DDT) |
| Regression | ~15 | API contract stability |
| E2E | ~12 | Full booking lifecycles |
| **Total** | **~87** | Against SQLite in-memory |

---

## Database Migrations

```bash
# Apply migrations (requires live PostgreSQL)
alembic upgrade head

# Generate new migration
alembic revision --autogenerate -m "add_column_x"

# Rollback
alembic downgrade -1
```

---

## Links

- **Author**: [github.com/itkdaniel](https://github.com/itkdaniel)
- **LinkedIn**: [linkedin.com/in/itkdaniel](https://linkedin.com/in/itkdaniel)
- **Portfolio**: NexusConsult Platform
- **Related**: [nexus-tax](../nexus-tax) · [nexus-search](../nexus-search) · [nexus-ai](../nexus-ai)
