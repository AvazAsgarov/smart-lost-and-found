# Project Status Report

**Project:** Smart Lost & Found (Topic 1 — AI-ENG-110 Capstone)
**Last updated:** 2026-05-22 (final completeness verification: Docker image builds, container smoke pass, 164/164 tests pass both locally and in-container, mypy + ruff clean)
**Submission deadline:** 2026-05-23 23:59 (UTC+4)

---

## 1. Current State of the Project

**Stage:** Implementation complete; comment refactor complete; verification pass complete. Entering deliverable-preparation phase.

**Codebase health:** Clean and verified.

- All nine planned implementation phases (foundation → bonus features → Docker → documentation) have been delivered.
- A full structural refactor was completed: the awkward `topic-1-lost-and-found/` wrapper was dissolved, the `ai/` library promoted to a root-level package, and all `sys.path` / `importlib` hacks removed.
- Every source file has a docstring; no `print()` calls for diagnostics; no hard-coded API keys.
- Linting (ruff), type checking (mypy), and the full pytest suite are wired into GitHub Actions CI.

**Readiness for continued development:** The project structure is fully organised and stable. Any further work is feature polish, verification, or deliverable preparation — not architectural change.

---

## 2. What Has Been Done So Far

### Project analysis and planning

- Read the entire project brief (`docs/SOFTWARE_PROJECT.pdf`, `docs/TOPIC.md`, `docs/ADVANCED_BONUSES.md`, `docs/COMMON_PITFALLS.md`, `docs/TIMELINE.md`).
- Produced a comprehensive implementation plan in `docs/PLAN.md` covering all phases, rubric points, and bonus targets.

### Phase 2 — Foundation

- `requirements.txt` — every dependency pinned (FastAPI 0.109.2, Pydantic 2.6.4, pytest 8.1.1, etc.).
- `.env.example` — complete environment-variable template; `.env` listed in `.gitignore`.
- `pyproject.toml` — pytest, ruff, and mypy configuration.
- `conftest.py` — root pytest configuration with `sys.path` setup and shared fixtures.
- `src/config.py` — `pydantic-settings` Settings class as the single source of truth.
- `src/models.py` — Pydantic domain and API response models (Item, MatchRecord, ItemResponse, etc.).

### Phase 3 — Storage Layer

- `src/storage/base.py` — `AbstractRepository` ABC + `save_image()` with UUID filenames and path-escape guard.
- `src/storage/sqlite_repo.py` — `SQLiteRepository` (aiosqlite), WAL mode, status index, `cursor.lastrowid`.
- `src/storage/repository.py` — `PostgreSQLRepository` (asyncpg) with connection pool and `RETURNING` clauses.
- `src/storage/__init__.py` — `build_repo()` factory selecting backend by URL prefix.

### Phase 4 — AI Service Layer

- `src/services/ai_service.py` — async wrappers `describe_item_async()` and `embed_async()` with:
  - Tenacity retries (exponential back-off, jitter)
  - `asyncio.wait_for` per-call timeout
  - In-process embedding cache
  - Rate-limiter acquisition and cost recording

### Phase 5 — API, CLI, Concurrency

- `src/api.py` — FastAPI app with all four required endpoints, two batch endpoints, health, lifespan, and exception handlers.
- `src/cli.py` — argparse CLI with `register-lost`, `register-found`, `search-matches`, `list`, `cost-report`.
- `src/concurrency/pipeline.py` — `run_with_semaphore()` and `register_batch()` for bounded concurrent execution.
- `src/core/matcher.py` — `find_matches()` with cosine ranking and reason enrichment.

### Phase 6 — Tests

- Eleven pytest files covering repository, AI service, matcher, API, pipeline, failures, failover, cost meter, rate limiter, smoke (provided), and skeleton imports.
- Fixtures centralised in `conftest.py`; fakes in `tests/fakes.py`.

### Phase 7 — Bonus Features

- `src/core/failover.py` — `FailoverVLM` and `FailoverEmbedder` multi-provider fallback (+3 pts).
- `src/services/cost_meter.py` — JSONL cost telemetry with pricing table and report formatter (+2 pts).
- `src/tracing.py` — OpenTelemetry setup with OTLP export and decorators (+2 pts).
- `src/concurrency/rate_limiter.py` — `TokenBudget` sliding 60-second window (+2 pts).
- `ui/app.py` — Streamlit Web UI for all core operations (+2 pts).
- `.github/workflows/ci.yml` — lint → typecheck → test → Docker build CI (+2 pts).
- `Dockerfile` — multi-stage build with non-root user (+1 pt).

### Phase 8 — Docker

- `Dockerfile` (builder + runtime stages).
- `.dockerignore`.
- `docker-compose.yml` (API + Streamlit UI + Jaeger).

### Phase 9 — Documentation

- `README.md` — quick start, API reference, CLI guide, Docker, config table.
- `docs/architecture.md` — ASCII architecture diagrams.
- `scripts/demo.py` — offline end-to-end demo using `FakeVLM`.
- `scripts/bench.py` — sequential vs concurrent benchmark.
- `PROJECT_STRUCTURE.md` — directory map and rationale.

### Structural Refactor

- Spec files (`SOFTWARE_PROJECT.pdf`, `.tex`) moved to `docs/`.
- `PLAN.md` moved to `docs/`.
- `templates/` consolidated under `docs/templates/`.
- `pull_request_template.md` placed at `.github/pull_request_template.md`.
- `topic-1-lost-and-found/` dissolved: `ai/` promoted to root package, `data/` → `data/samples/`, smoke tests → `tests/`, `TOPIC.md` → `docs/`, demo → `scripts/`.
- `tests/fakes.py` created as canonical location for `FakeVLM` / `FakeEmbedder`.
- All `sys.path` hacks and `importlib` dynamic loading removed.

### Comment / Docstring Refactor and Verification Pass

- Removed every banner / separator comment (``# ----- ... -----``) across every source and test file.
- Removed inline explanatory comments throughout, replacing the most useful ones with proper docstrings on the corresponding module, class, function, or attribute.
- Added Google-style docstrings to every public class, function, method, fixture, and module that lacked one.
- Created `tests/__init__.py` so `from tests.fakes import ...` resolves as a regular package import rather than a dynamic load.
- Moved `from src.config import settings` to module level in `src/storage/base.py` so tests can monkeypatch it.
- Clamped cosine similarity scores in `src/core/matcher.py` to `[0, 1]` to absorb float32 rounding noise that previously violated the Pydantic `MatchRecord.score` constraint (`<= 1.0`).
- Fixed two test mocks (`tests/test_ai_service.py`, `tests/test_failures.py`) so they match the real call signatures.
- Replaced Unicode arrows/em-dashes in user-facing print output with ASCII so the demo and CLI run cleanly under Windows cp1252.
- **Verified: `pytest tests/` reports 163 passed, 0 failed.**
- **Verified: `python scripts/demo.py` runs the full pipeline end-to-end offline (registration, matching, cost report).**
- **Verified: `from src.api import app` imports cleanly with all 11 routes registered.**
- **Verified: `python -m src.cli --help` prints the expected command list.**

---

## 3. What Is Currently In Progress

- Nothing actively in flight. The system is at a known-good, fully-verified checkpoint.

---

## 4. What Has Not Been Done Yet (Remaining Work)

### Core features not implemented

- None. All ten rubric build requirements are covered.

### Secondary features / enhancements

- The OpenTelemetry decorators (`@traced_ai_call`, `@traced_db_op`) exist in `src/tracing.py` and are applied to both storage implementations and the AI service layer.

### Testing / validation tasks

- ✅ `pytest tests/` — 164 passed, 0 failed.
- ✅ `python scripts/demo.py` — full offline pipeline runs.
- ✅ `pytest --cov=src` — 71% line coverage on `src/` (recorded in README).
- ✅ `mypy src/` — clean (no issues found in 19 source files).
- ✅ `ruff check src/ tests/ scripts/ ui/` — clean (all checks passed).
- ✅ `scripts/bench.py --n 6` — sequential vs concurrent table generated (~3.9× speedup).
- ✅ `docker build .` — multi-stage image (Python 3.12, non-root user, HEALTHCHECK) builds clean.
- ✅ Docker container smoke — `/health` returns `{"status":"ok","db":"ok"}`, `/docs` returns 200, full pytest suite passes inside the runtime image.

### Deployment / finalisation tasks

- Fill in `docs/templates/REPORT_TEMPLATE.tex` — full project report.
- Fill in `docs/templates/SLIDES_TEMPLATE.tex` — defence slides.
- Fill in `docs/templates/CONTRIBUTION_STATEMENT.md` — signed by all team members.
- Tag the final commit on `main` as `v1.0-final` and push the tag.
- Send submission email with GitHub URL, report PDF, slides PDF, and contribution statement.

### Bonus / optional improvements

- ✅ `tests/test_smoke_e2e.py` — end-to-end pipeline smoke test (register lost + register found + match) covered.
- ✅ Tracing decorators applied to all repository and AI-service methods.

---

## 5. Project Structure Overview

The project follows a layered, intention-revealing structure with clear separation of concerns. See `PROJECT_STRUCTURE.md` for the full map.

| Folder | Purpose |
| --- | --- |
| `ai/` | Provided AI library (VLM + embedding + similarity). Root-level package — `from ai import ...` works without configuration. |
| `src/` | Application source code, organised by architectural layer (`core/`, `services/`, `storage/`, `concurrency/`). |
| `tests/` | Full pytest suite. Includes our tests, the provided smoke tests, and `fakes.py` as canonical fake-provider location. |
| `ui/` | Streamlit Web UI. |
| `scripts/` | Operational scripts: benchmark, end-to-end demo, provided AI demo. |
| `data/samples/` | Provided reference images (committed). Runtime uploads go to `data/images/` (gitignored). |
| `docs/` | All documentation: architecture, specs, planning, templates. |
| `.github/` | CI workflow and PR template. |
| Root | Conventional config files only (`Dockerfile`, `pyproject.toml`, `requirements.txt`, `README.md`, `conftest.py`, etc.). |

**Why this structure:** every folder has a single intentional purpose; the AI library is importable at the root with zero path manipulation; the storage and service layers can be swapped or extended without touching presentation code; documentation is consolidated so graders find specs, plans, and diagrams in one place.

---

## 6. Next Immediate Steps

In priority order:

1. **Fill in the report and slides templates** in `docs/templates/`. (Skipped per user instructions)
2. **Tag and push `v1.0-final`** once everything above is green. (Skipped per user instructions)

---

## 7. Notes for Continuation

### Architectural assumptions and decisions

- **Async-first.** All I/O — HTTP, DB, AI — is async. Synchronous AI SDKs are bridged with `asyncio.to_thread()`.
- **Repository pattern.** All DB access goes through `AbstractRepository`; swapping SQLite for PostgreSQL is a configuration change, not a code change.
- **Single config source.** `src/config.py` (pydantic-settings) is the only place env vars are read. No magic strings elsewhere.
- **No bare `print()` for diagnostics.** All diagnostic output uses `logging`. `print()` is reserved for CLI/UI user-facing output.
- **UUID image filenames.** Prevents path-traversal attacks regardless of user-supplied filenames.
- **`ai/` is treated as a third-party library.** Imported, never modified.

### Rules to follow in further development

- Maintain docstrings on all modules, classes, and public functions.
- Keep any new business logic out of `api.py` / `cli.py` / `ui/app.py` — those are presentation entry points only.
- New DB methods go on `AbstractRepository` first, then concrete implementations.
- New AI integrations go through `src/services/ai_service.py` so retries, timeouts, caching, and cost recording apply uniformly.
- Tests for new code go in `tests/test_<module>.py` with a matching name to the module being tested.
- Run `ruff check`, `mypy`, and `pytest` locally before pushing — CI will fail otherwise.

### Risks to track

- **API key handling.** Real keys must never be committed. `.env` is in `.gitignore`; `.env.example` lists keys with empty values only.
- **Provided smoke tests.** `tests/test_ai_smoke.py` is a grading contract; do not modify or skip it.
- **Pinned dependencies.** Do not unpin versions in `requirements.txt` to "get the latest"; CI reproducibility depends on the pinned set.

### Continuity contract

This file (`PROJECT_STATUS.md`) is the single source of truth for project status. Update it at the end of each work session with what changed, what is now in progress, and what the next step is. Do not let it go stale — if it disagrees with the codebase, fix the document.
