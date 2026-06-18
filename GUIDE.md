# nexus-booking — Developer Guide

Complete reference for developing, testing, and operating `nexus-booking`.

---

## Table of Contents

1. [Local Development](#local-development)
2. [Environment Variables](#environment-variables)
3. [Database Setup](#database-setup)
4. [Running Tests](#running-tests)
5. [Adding New Endpoints](#adding-new-endpoints)
6. [Availability Index Deep-Dive](#availability-index-deep-dive)
7. [Email Service](#email-service)
8. [Auth System](#auth-system)
9. [Error Handling](#error-handling)
10. [Performance Notes](#performance-notes)

---

## Local Development

### Prerequisites

- Python 3.12+
- PostgreSQL 15+ (or use Docker)

### Setup

```bash
git clone https://github.com/itkdaniel/nexus-booking.git
cd nexus-booking
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
# Edit .env with your database URL and JWT secret
```

### Start the service

```bash
# Dev mode (hot reload)
uvicorn app.main:app --reload --port 8002

# Production mode
uvicorn app.main:app --host 0.0.0.0 --port 8002 --workers 4
```

### With Docker

```bash
docker compose up --build          # Postgres + service
docker compose logs -f booking     # Stream logs
docker compose exec booking sh     # Shell into container
```

---

## Environment Variables

| Variable | Type | Default | Required | Description |
|----------|------|---------|----------|-------------|
| `DATABASE_URL` | str | `postgresql+asyncpg://...` | Yes | Async SQLAlchemy connection URL |
| `JWT_SECRET` | str | `change-me` | **Production** | HMAC signing key — must match main portfolio |
| `JWT_ALGORITHM` | str | `HS256` | No | Token signing algorithm |
| `PORT` | int | `8002` | No | HTTP port |
| `DEBUG` | bool | `false` | No | Enable SQLAlchemy query logging |
| `EMAIL_ENABLED` | bool | `false` | No | Enable SMTP email; console-only if false |
| `SMTP_HOST` | str | `""` | Email | SMTP server hostname |
| `SMTP_PORT` | int | `587` | Email | SMTP server port |
| `SMTP_SECURE` | bool | `false` | Email | Use TLS (port 465) |
| `SMTP_USER` | str | `""` | Email | SMTP username |
| `SMTP_PASSWORD` | str | `""` | Email | SMTP password |
| `FROM_NAME` | str | `NexusConsult Booking` | No | Email sender name |
| `FROM_EMAIL` | str | `noreply@nexusconsult.dev` | No | Email sender address |
| `ADMIN_EMAIL` | str | `admin@nexusconsult.dev` | No | Admin notification target |
| `AVAILABILITY_WINDOW_DAYS` | int | `30` | No | Days ahead in the slot index |
| `CORS_ORIGINS` | list[str] | `["*"]` | No | JSON array of allowed CORS origins |
| `PORTFOLIO_URL` | str | `http://localhost:5000` | No | Main portfolio base URL |

---

## Database Setup

### Using Alembic (production)

```bash
# Run all pending migrations
alembic upgrade head

# Create a new migration after schema change
alembic revision --autogenerate -m "add_notes_column"

# Inspect current state
alembic current
alembic history

# Roll back one step
alembic downgrade -1
```

### Dev / test (auto-create)

In dev and test, `create_tables()` is called at startup via the lifespan
context — it issues `CREATE TABLE IF NOT EXISTS` for all models. This requires
no Alembic setup for local hacking.

---

## Running Tests

### All tests

```bash
pytest
```

### By marker

```bash
pytest -m unit           # Pure unit tests (fast, no I/O)
pytest -m bdd            # Gherkin BDD scenarios
pytest -m property       # Hypothesis property tests
pytest -m regression     # API contract tests
pytest -m e2e            # End-to-end lifecycle tests
```

### With coverage

```bash
pytest --cov=app --cov-report=term-missing
pytest --cov=app --cov-report=html && open htmlcov/index.html
```

### Test architecture

All tests use SQLite in-memory (`aiosqlite`) — no external database needed.
The `create_app(settings)` factory is used to inject test settings:

```python
# conftest.py
app = create_app(Settings(database_url="sqlite+aiosqlite:///:memory:"))
# Override DB dependency
app.dependency_overrides[get_db_dep] = override_db
```

---

## Adding New Endpoints

1. **Define schema** in `app/models.py` (Pydantic request + response models)
2. **Write the route** in `app/routers/bookings.py` (or a new router file)
3. **Register the router** in `app/main.py` via `app.include_router(...)`
4. **Write unit tests** in `tests/unit/`
5. **Write regression tests** to lock the response contract in `tests/regression/`
6. **Write a BDD feature** in `tests/bdd/features/`

### Route template

```python
@router.post("/v1/my-resource", response_model=MyResponse, status_code=201)
async def create_my_resource(
    payload: MyCreate,
    db: AsyncSession = Depends(get_db_dep),
    _admin: dict = Depends(require_admin),  # or require_auth for auth-only
) -> MyResponse:
    ...
```

---

## Availability Index Deep-Dive

The `AvailabilityIndex` is an asyncio-safe in-memory data structure:

```python
_index: Dict[str, Set[str]]   # "YYYY-MM-DD" → {"09:00", "09:15", ...}
_lock: asyncio.Lock           # protects concurrent writes
```

### Lifecycle

```
Startup → build() → scans DB for existing bookings → populates _index
Request → mark_booked(date, time) → set.discard()  # O(1)
Cancel  → free_slot(date, time)   → set.add()      # O(1)
Query   → get_slots(date)         → sorted(set)    # O(k log k)
```

### Business hours

- Morning block: 09:00 – 11:45 (16 slots × 15 min)
- Afternoon block: 13:00 – 16:45 (16 slots × 15 min)
- Lunch (12:00 – 12:45): excluded
- Weekends: excluded from index

### Extending the window

Change `AVAILABILITY_WINDOW_DAYS` in `.env`. The index is rebuilt at next startup.
To rebuild without restart, call `idx.build(booked_map)` directly.

---

## Email Service

Email is dispatched via `BackgroundTasks` so it never blocks the booking response.
The email service uses `asyncio.gather()` to send user confirmation + admin notification
concurrently:

```python
background_tasks.add_task(dispatch_booking_emails, booking_data)
# Inside dispatch_booking_emails:
await asyncio.gather(
    send_email(user_payload),
    send_email(admin_payload),
)
```

When `EMAIL_ENABLED=false` (default), emails are logged to stdout — no SMTP required.
To enable real email:

```env
EMAIL_ENABLED=true
SMTP_HOST=smtp.sendgrid.net
SMTP_PORT=587
SMTP_USER=apikey
SMTP_PASSWORD=<your-sendgrid-key>
```

---

## Auth System

The service accepts HMAC-SHA256 JWTs issued by the main portfolio gateway.
Token format: standard JWT with `{"sub": userId, "role": "admin"|"user", "exp": ...}`.

### FastAPI dependencies

```python
# Any authenticated user
@router.get("/protected", dependencies=[Depends(require_auth)])

# Admin-only
@router.delete("/admin-only", dependencies=[Depends(require_admin)])

# Get user from token
@router.get("/me")
async def me(user: dict = Depends(require_auth)):
    return {"sub": user["sub"], "role": user["role"]}
```

### Generating tokens for testing / dev

```python
from app.auth import generate_token
token = generate_token({"sub": "user-id", "role": "admin"}, secret="your-secret")
```

---

## Error Handling

All endpoints return a standard error envelope on failure:

```json
{
  "error": "Time slot not available",
  "code": "SLOT_UNAVAILABLE",
  "details": {"date": "2025-06-15", "time": "09:00"},
  "request_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

### Error codes

| Code | HTTP | Meaning |
|------|------|---------|
| `SLOT_UNAVAILABLE` | 409 | The requested time slot is already booked |
| `NOT_FOUND` | 404 | Booking ID does not exist |
| `UNAUTHORIZED` | 401 | No valid JWT provided |
| `FORBIDDEN` | 403 | JWT valid but role insufficient |
| `INVALID_DATE` | 400 | Date string format error |
| `INVALID_RANGE` | 400 | start > end in availability query |
| `RANGE_TOO_LARGE` | 400 | Availability range exceeds 60 days |
| `INTERNAL_ERROR` | 500 | Unhandled exception |

---

## Performance Notes

| Operation | Complexity | Notes |
|-----------|-----------|-------|
| Startup slot index build | O(n) | n = existing bookings |
| Availability slot lookup | O(1) | Dict key lookup |
| Availability range query | O(d) | d = days in range |
| Booking creation | O(1) | Single DB insert + set.discard() |
| Booking cancellation | O(1) | DB update + set.add() |
| Admin list bookings | O(n) | Full table scan + serialize |
| Email dispatch | O(1) wall-clock | Concurrent via asyncio.gather() |

The connection pool is tuned for a single-service deployment:
`pool_size=2, max_overflow=8` — adjust for high-concurrency deployments.
