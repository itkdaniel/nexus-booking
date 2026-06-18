# Contributing to nexus-booking

Thank you for your interest! This guide explains how to contribute code,
tests, and documentation.

---

## Branch Strategy

| Branch | Purpose |
|--------|---------|
| `main` | Production-ready code. Protected. PRs only. |
| `develop` | Integration branch. Merge feature branches here first. |
| `feat/<name>` | New feature (e.g. `feat/reschedule-endpoint`) |
| `fix/<name>` | Bug fix (e.g. `fix/double-booking-race`) |
| `chore/<name>` | Non-functional work (e.g. `chore/update-deps`) |
| `docs/<name>` | Documentation only |

---

## Development Workflow

```bash
# 1. Fork and clone
git clone https://github.com/itkdaniel/nexus-booking.git
cd nexus-booking

# 2. Create feature branch
git checkout -b feat/my-feature

# 3. Install dev deps
pip install -r requirements-dev.txt

# 4. Make changes + write tests

# 5. Lint
ruff check app/ tests/

# 6. Run tests
pytest

# 7. Commit (Conventional Commits)
git commit -m "feat(availability): add multi-timezone slot support"

# 8. Push and open PR
git push origin feat/my-feature
```

---

## Commit Message Format

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <short description>

[optional body]

[optional footer]
```

### Types

| Type | Description |
|------|-------------|
| `feat` | New feature |
| `fix` | Bug fix |
| `docs` | Documentation only |
| `test` | Adding or improving tests |
| `refactor` | Code restructure without feature change |
| `perf` | Performance improvement |
| `chore` | Maintenance (deps, build, CI) |
| `ci` | CI/CD pipeline changes |

### Examples

```
feat(bookings): add reschedule endpoint
fix(availability): prevent double-booking under concurrent load
test(bdd): add cancel_booking scenario
docs(readme): update API reference table
chore(deps): bump fastapi to 0.112.0
```

---

## Code Standards

### Python style

- Python 3.12+, type hints on all public functions
- `ruff` for linting (`ruff check app/ tests/`)
- Maximum line length: 100 chars
- Docstrings on all public classes and functions

### Async

- All I/O must be async — no `time.sleep()`, no `requests` (use `httpx`)
- Use `asyncio.gather()` for concurrent async operations
- Use `anyio.to_thread.run_sync()` for CPU-bound work

### Tests

- Every new endpoint needs:
  - At least one unit test for the happy path
  - At least one unit test for each error case
  - A regression test to lock the response shape
  - A BDD scenario if it involves user-visible behaviour
- Tests must pass in isolation (no shared state between tests)
- Use fixtures — never hardcode IDs

---

## Pull Request Process

1. Open a PR against `develop` (not `main`)
2. Fill in the PR description template
3. All CI checks must pass (lint → unit → bdd → property → regression → e2e)
4. At least one code review approval required
5. Squash merge — keep `main` history clean

---

## Adding Tests

### Unit test

Place in `tests/unit/test_<module>.py`. Mark with `@pytest.mark.unit`.
No external I/O allowed — mock everything.

### BDD scenario

1. Add a scenario to an existing `.feature` file or create a new one in
   `tests/bdd/features/`
2. Implement step functions in `tests/bdd/steps/booking_steps.py`
3. Mark the test function with `@pytest.mark.bdd`

### Property test

Add to `tests/property/test_date_properties.py`.
Use `@given(...)` from Hypothesis.
Mark with `@pytest.mark.property`.

### Regression test

Add to `tests/regression/test_contracts.py`.
Focus on the *shape* of the response, not the data.
Mark with `@pytest.mark.regression`.

---

## Reporting Issues

Open a GitHub issue with:
- Description of the bug / feature request
- Steps to reproduce (for bugs)
- Expected vs actual behaviour
- Python version and OS

---

## Contact

- **GitHub**: [github.com/itkdaniel](https://github.com/itkdaniel)
- **LinkedIn**: [linkedin.com/in/itkdaniel](https://linkedin.com/in/itkdaniel)
