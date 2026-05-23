# Contribution Statement

**Team:** Avaz / Kazim / Gulnar
**Topic:** Topic 1 — Smart Lost & Found
**Repository:** [https://github.com/AvazAsgarov/smart-lost-and-found](https://github.com/AvazAsgarov/smart-lost-and-found)
**Final tag:** `v1.0-final`
**Submission date:** 2026-05-23

---

## How to fill this in

This is the single piece of evidence we use to assess **individual contribution** within the team. Rules:

1. Every member writes their own three subsections (Owned, Co-owned, Reviewed).
2. **Be specific.** "Worked on the backend" is not acceptable; "implemented `src/services/ai_service.py` and `src/concurrency/pipeline.py`, owned PRs #4, #7, #11" is.
3. The committed-percentages must add to 100% and approximately match `git shortlog -sn` on the `main` branch.
4. All three members must sign at the bottom. Unsigned submissions are returned ungraded.

If one member contributed less than 10% without a documented reason (illness, emergency), the team loses 5 points automatically per the rubric.

---

## Member A — Avaz Asgarov (`@AvazAsgarov`)

**Role:** Platform & Architecture Lead

**Owned (sole author of these files / PRs):**
- `src/storage/base.py` — `AbstractRepository` ABC + shared `save_image()` helper with path-escape guard
- `src/storage/sqlite_repo.py` — async SQLite backend (aiosqlite, WAL mode, status index)
- `src/storage/repository.py` — PostgreSQL production backend (asyncpg, connection pool)
- `src/storage/__init__.py` — `build_repo()` factory
- `src/api.py` — FastAPI app, 7 routes, lifespan management, exception handlers
- `src/concurrency/pipeline.py` — `run_with_semaphore()` and `register_batch()`
- `src/core/matcher.py` — `find_matches()` and reason-text composition
- `Dockerfile` — multi-stage build, non-root user, HEALTHCHECK
- `docker-compose.yml` — api + ui + jaeger services
- Project root structure, `conftest.py`, release tagging (`v1.0-final`)

**Co-owned (paired or substantially edited):**
- `src/config.py` (with Kazim) — pydantic-settings configuration
- `src/models.py` (with Kazim) — domain models and API response schemas
- `src/core/failover.py` (with Kazim) — provider chain orchestration

**Reviewed (PRs reviewed and merged):**
- All AI integration PRs (Kazim's work)
- All testing / CI / UI PRs (Gulnar's work)
- Final release tag and Docker validation

**Approximate share of commits:** 35%

---

## Member B — Kazim Mammadli (`@KazimMammadli`)

**Role:** AI Integration Lead

**Owned (sole author of these files / PRs):**
- `src/services/ai_service.py` — async wrappers around `ai/` with retries, timeouts, cache, rate limit, cost meter integration
- `src/services/cost_meter.py` — JSONL cost telemetry, pricing table, report formatter
- `src/concurrency/rate_limiter.py` — `TokenBudget` with 60-second sliding window
- `src/core/failover.py` — `FailoverVLM` and `FailoverEmbedder` (paired with Avaz)
- `src/tracing.py` — OpenTelemetry setup + `@traced_ai_call` / `@traced_db_op` decorators
- `.env.example` — environment variable template with provider configuration

**Co-owned (paired or substantially edited):**
- `src/config.py` (with Avaz) — environment variable schema
- `src/models.py` (with Avaz) — `MatchRecord` and `MatchResponse`
- `src/api.py` (with Avaz) — exception handlers for `ProviderError` and `TimeoutError`

**Reviewed (PRs reviewed and merged):**
- All storage / API / concurrency PRs (Avaz's work)
- All testing / CI / UI PRs (Gulnar's work)
- Cost meter integration tests

**Approximate share of commits:** 33%

---

## Member C — Gulnar Babazade (`@gulnarbabazade`)

**Role:** Quality & UX Lead

**Owned (sole author of these files / PRs):**
- `tests/` — full pytest suite (164 tests, 71% coverage)
  - `tests/test_api.py`, `tests/test_repository.py`, `tests/test_matcher.py`
  - `tests/test_ai_service.py`, `tests/test_failover.py`, `tests/test_cost_meter.py`
  - `tests/test_rate_limiter.py`, `tests/test_pipeline.py`, `tests/test_failures.py`
  - `tests/test_smoke_e2e.py`, `tests/fakes.py` (FakeVLM + FakeEmbedder)
- `src/cli.py` — argparse CLI with 5 subcommands
- `ui/app.py` — Streamlit web UI (5 pages, sidebar navigation)
- `scripts/demo.py` — offline end-to-end demo
- `scripts/bench.py` — sequential vs concurrent benchmark
- `.github/workflows/ci.yml` — GitHub Actions CI pipeline (lint → typecheck → test → docker build)
- `README.md` — top-level documentation

**Co-owned (paired or substantially edited):**
- `src/api.py` (with Avaz) — request validation and response shaping
- `docs/REPORT.tex` (with all members) — final report
- `docs/SLIDES.tex` (with all members) — presentation deck

**Reviewed (PRs reviewed and merged):**
- All storage / API / concurrency PRs (Avaz's work)
- All AI integration PRs (Kazim's work)
- End-to-end smoke test runs against every PR before merge

**Approximate share of commits:** 32%

---

## AI tool disclosure (also in §10 of the report)

We used **Claude Code** (Anthropic's terminal-based AI coding assistant) as a development tool throughout the project. Each item below lists the module, the assistant, and what the team did with the output. Every line was reviewed and adapted before commit.

| Module / file | Assistant | What we did with it |
|---|---|---|
| `src/core/failover.py` | Claude Code | Drafted the ranked-provider iteration pattern; we rewrote the constructor signature, replaced the custom exception with a re-raised `ProviderError`, and added the two log lines the incident analysis depends on. |
| `src/concurrency/rate_limiter.py` | Claude Code | Sketched the initial sliding-window design; we replaced an early `queue.Queue` draft with a `collections.deque` guarded by an `asyncio.Lock`, and wrote the 60-second expiry logic ourselves. |
| `tests/` (multiple files) | Claude Code | Helped with fixture parameter signatures and repeated mock setup; every test was read line-by-line before being committed. |
| `docs/REPORT.tex`, `docs/SLIDES.tex`, `README.md` | Claude Code | Helped draft and structure documentation; the team edited every section for tone, accuracy, and project-specific detail before submission. |
| Type-hint cleanup (mypy clean across 19 source files) | Claude Code | Suggested type annotations; we accepted/rewrote each suggestion after reviewing the inference. |
| Debugging the failover/tenacity nesting bug | Claude Code | Traced the failing call-count assertion and proposed the nested-policy fix; we implemented and verified the fix ourselves. |

We affirm that we **can defend every line of code** in this repository during the oral defense. "The AI wrote it" is not an answer we will use.

---

## Signatures

By signing below, we affirm that:
- The contributions described above are accurate.
- The commit percentages reflect actual work, not artificially split commits.
- Every line of code in the repository can be defended by at least one team member.
- AI assistant usage has been disclosed as described above.

| Member           | Date       |
|------------------|------------|
| Avaz Asgarov     | 23.05.2026 |
| Kazim Mammadli   | 23.05.2026 |
| Gulnar Babazade  | 23.05.2026 |