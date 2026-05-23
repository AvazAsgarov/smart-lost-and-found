# Project Structure

This document explains the final directory layout of the Smart Lost & Found project, the purpose of each directory, and the rationale behind the organisation.

---

## Directory Tree

```text
AI Academy Final/
│
├── ai/                         Provided AI library — root-level Python package
│   ├── providers/              VLM + embedding provider implementations
│   │   ├── base.py             VLMProvider / EmbeddingProvider ABCs + ProviderError
│   │   ├── anthropic.py        Claude VLM provider
│   │   ├── openai.py           GPT-4o VLM + text-embedding provider
│   │   ├── google.py           Gemini VLM + embedding provider
│   │   └── factory.py          get_vlm() / get_embedder() factories
│   ├── schemas.py              ItemDescription schema + ITEM_DESCRIPTION_SCHEMA
│   ├── similarity.py           cosine(), top_k(), MatchResult
│   ├── vlm.py                  describe_item() entry point
│   └── embedding.py            embed() entry point
│
├── src/                        Application source — our code
│   ├── api.py                  FastAPI HTTP server (all endpoints + lifespan)
│   ├── cli.py                  argparse CLI (register-lost/found, search, list, cost-report)
│   ├── config.py               pydantic-settings Settings (single source of truth)
│   ├── models.py               Pydantic domain models (Item, MatchRecord, ItemResponse, …)
│   ├── tracing.py              OpenTelemetry setup + @traced_ai_call / @traced_db_op
│   │
│   ├── core/                   Pure domain / business logic — no I/O
│   │   ├── failover.py         FailoverVLM, FailoverEmbedder — multi-provider fallback
│   │   └── matcher.py          find_matches() — cosine similarity ranking
│   │
│   ├── services/               Application services — orchestrate AI + side-effects
│   │   ├── ai_service.py       describe_item_async(), embed_async() — retried, cached
│   │   └── cost_meter.py       CostMeter — JSONL cost telemetry + report generation
│   │
│   ├── storage/                Data access layer — repository pattern
│   │   ├── base.py             AbstractRepository ABC + save_image() (UUID filename)
│   │   ├── sqlite_repo.py      SQLiteRepository (aiosqlite) — development default
│   │   └── repository.py       PostgreSQLRepository (asyncpg) — production
│   │
│   └── concurrency/            Async concurrency utilities
│       ├── pipeline.py         run_with_semaphore(), register_batch()
│       └── rate_limiter.py     TokenBudget — sliding-window TPM enforcement
│
├── tests/                      Full pytest test suite
│   ├── fakes.py                FakeVLM, FakeEmbedder — canonical fake providers
│   ├── test_ai_smoke.py        Provided smoke tests (grading contract — must pass)
│   ├── test_repository.py      SQLiteRepository integration tests
│   ├── test_ai_service.py      Retry, cache, timeout, empty-text rejection
│   ├── test_matcher.py         Ranking, status direction, reason enrichment
│   ├── test_api.py             FastAPI endpoint tests (TestClient + AsyncMock)
│   ├── test_pipeline.py        Semaphore bounds, exception-as-value, concurrency speed
│   ├── test_failures.py        Failure injection: 400, 413, 502, 504, 404, 422
│   ├── test_failover.py        FailoverVLM and FailoverEmbedder chaos tests
│   ├── test_cost_meter.py      Pricing lookups, JSONL persistence, report formatting
│   └── test_rate_limiter.py    TokenBudget: acquire, window expiry, singleton
│
├── ui/
│   └── app.py                  Streamlit Web UI — registration, search, browse, cost report
│
├── scripts/
│   ├── bench.py                Sequential vs concurrent throughput benchmark
│   ├── demo.py                 Offline end-to-end demo (FakeVLM, no API keys needed)
│   └── demo_ai.py              Provided AI module demo script
│
├── data/
│   ├── samples/                Provided sample images (committed to git)
│   │   ├── lost/               5 sample lost-item images
│   │   └── found/              7 sample found-item images
│   └── images/                 Runtime image uploads (gitignored, created by the app)
│
├── docs/                       All project documentation
│   ├── architecture.md         ASCII architecture diagrams (system, data flow, concurrency)
│   ├── TOPIC.md                Project topic description (provided by instructor)
│   ├── ADVANCED_BONUSES.md     Bonus feature rubric (provided by instructor)
│   ├── COMMON_PITFALLS.md      Grading pitfalls to avoid (provided by instructor)
│   ├── GIT_WORKFLOW.md         Branch model and PR rules (provided by instructor)
│   ├── TIMELINE.md             12-day schedule and milestone gates (provided by instructor)
│   ├── PLAN.md                 Internal implementation plan and phase checklist
│   ├── SOFTWARE_PROJECT.pdf    Project specification document (provided by instructor)
│   ├── SOFTWARE_PROJECT.tex    LaTeX source of the specification (provided by instructor)
│   └── templates/              Provided templates for student deliverables
│       ├── CONTRIBUTION_STATEMENT.md
│       ├── Dockerfile.template
│       ├── REPORT_TEMPLATE.pdf / .tex
│       ├── SLIDES_TEMPLATE.pdf / .tex
│       └── STUDENT_README_TEMPLATE.md
│
├── artefacts/                  Runtime-generated output (gitignored except .gitkeep)
│   └── .gitkeep
│
├── .github/
│   ├── workflows/
│   │   └── ci.yml              GitHub Actions: lint → typecheck → test → docker build
│   └── pull_request_template.md  Auto-fills every new GitHub PR
│
├── Dockerfile                  Multi-stage build (builder + runtime, non-root user)
├── docker-compose.yml          Full stack: API + Streamlit UI + Jaeger
├── .dockerignore               Excludes dev artefacts from Docker build context
│
├── pyproject.toml              pytest, ruff, and mypy configuration
├── requirements.txt            Pinned runtime + dev dependencies
├── .env.example                Environment variable template (commit this, never .env)
├── .gitignore                  Excludes secrets, runtime data, caches
│
├── conftest.py                 Root pytest conftest — shared fixtures (fake_vlm, sample_image)
├── README.md                   Project overview, quick start, API reference, config table
└── PROJECT_STRUCTURE.md        This file
```

---

## Why Each Directory Exists

### `ai/`

The provided AI library, promoted to a **root-level Python package**. Because it sits at the project root, `from ai import describe_item` just works — no `sys.path` hacks, no extra directory on `PYTHONPATH`, no `importlib` gymnastics. All of our code in `src/` imports from here.

This used to live inside a folder called `topic-1-lost-and-found/`. That wrapper is gone; only the library itself remains.

### `src/`

Everything we wrote. Organised by architectural layer so each layer can be understood, tested, and extended independently:

| Sub-package | Responsibility |
| --- | --- |
| `core/` | Pure Python business logic. No I/O, no frameworks. Independently testable. |
| `services/` | Orchestrate AI calls with retries, caching, rate-limiting, and cost recording. |
| `storage/` | Repository pattern — SQLite (dev) or PostgreSQL (prod) behind a shared ABC. |
| `concurrency/` | Async utilities: semaphore-bounded parallelism and token-rate-limiter. |

`api.py`, `cli.py`, `config.py`, `models.py`, and `tracing.py` sit at the `src/` root because they are application-wide concerns, not domain-specific sub-packages.

### `tests/`

One test file per source module, plus two special files:

- **`fakes.py`** — the canonical location for `FakeVLM` and `FakeEmbedder`. Every script and fixture imports from here; there is no dynamic `importlib` loading of a buried conftest.
- **`test_ai_smoke.py`** — the provided grading smoke tests, integrated alongside our own tests so a single `pytest tests/` run covers everything.

### `data/`

Split into two clear concerns:

- `data/samples/` — provided reference images, committed to git, used by `scripts/bench.py` and `scripts/demo.py` for offline runs.
- `data/images/` — runtime uploads written by the application, gitignored (created on first run).

### `docs/`

All documentation in one place: instructor-provided guides and specs, our generated architecture diagrams, our implementation plan, and student deliverable templates. Keeping docs out of the source tree means a grader can find every document without navigating code directories.

### `.github/`

Standard GitHub directory. Two files:

- `workflows/ci.yml` — CI pipeline triggered on push and PR.
- `pull_request_template.md` — GitHub reads this path automatically to pre-fill the PR description body.

### Root-level config files

`Dockerfile`, `docker-compose.yml`, `pyproject.toml`, `requirements.txt`, `.env.example`, `.gitignore`, and `conftest.py` all live at the root because their respective tools (`docker`, `pytest`, `ruff`, `mypy`) look for them there by convention.

---

## Key Structural Decisions

| Decision | Rationale |
| --- | --- |
| `ai/` at project root | Eliminates `sys.path` manipulation. `from ai import ...` works everywhere without configuration. |
| `tests/fakes.py` as canonical fake location | One import path for tests, scripts, and benchmarks. No dynamic `importlib` loading. |
| `AbstractRepository` ABC | Swapping SQLite → PostgreSQL requires zero service-layer changes. |
| `src/config.py` as single settings source | No env-var reads scattered through the codebase; all settings are typed and validated at startup. |
| `data/samples/` vs `data/images/` | Clear separation between provided test data (committed) and runtime uploads (ignored). |
| All docs under `docs/` | Single place for graders and teammates to find specs, plans, and diagrams. |
