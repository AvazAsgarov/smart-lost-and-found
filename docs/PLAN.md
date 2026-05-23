# Smart Lost & Found — Complete Implementation Plan

> Topic 1 · AI-ENG-110 Software Engineering · AI Academy Spring 2026  
> 3-person team · Full quality build including all bonus opportunities

---

## Table of Contents

1. [Project Understanding](#1-project-understanding)
2. [Architecture Decisions](#2-architecture-decisions)
3. [Technology Stack](#3-technology-stack)
4. [Final Folder Structure](#4-final-folder-structure)
5. [Data Models & Contracts](#5-data-models--contracts)
6. [Implementation Phases](#6-implementation-phases)
7. [Dependency Graph](#7-dependency-graph)
8. [Bonus Feature Strategy](#8-bonus-feature-strategy)
9. [Testing Strategy](#9-testing-strategy)
10. [Docker & Deployment Strategy](#10-docker--deployment-strategy)
11. [Documentation & Presentation Plan](#11-documentation--presentation-plan)
12. [Risk Register](#12-risk-register)
13. [Quality Checklist](#13-quality-checklist)

---

## 1. Project Understanding

### What the AI module provides (do NOT touch)
- `ai.describe_item(image_path, user_text, *, vlm=None) → ItemDescription` — VLM call, structured output
- `ai.embed(text, *, embedder=None) → np.ndarray` — unit-normalized embedding vector
- `ai.cosine(a, b) → float` — cosine similarity
- `ai.top_k(query_vec, candidates, k=3) → list[MatchResult]` — sorted top-k matches
- `ai.schemas.ItemDescription`, `ai.schemas.MatchResult` — Pydantic v2 models
- `ai.providers.base.VLMProvider`, `EmbeddingProvider`, `ProviderError` — abstract interfaces
- `ai.providers.factory.get_vlm()`, `get_embedder()` — env-driven factory functions
- 30 contract smoke tests that must always pass

### What we build (the SE layer)
The full software engineering shell around that AI library: storage, API, CLI, concurrency, retries, caching, logging, validation, tests, Docker, monitoring, and documentation.

### Grading rubric weights
| Category | Points | Key wins |
|---|---|---|
| Correctness & Functionality | 22 | End-to-end demo works, smoke tests pass |
| Architecture & OOP | 13 | Clean separation, typed interfaces, no naked dicts |
| Concurrency & Performance | 10 | Benchmark table, semaphore, async pipeline |
| Robustness & Error Handling | 8 | Retries, timeouts, validation, no hard-coded keys |
| Testing & Code Quality | 7 | ≥60% coverage, all offline, type hints, no TODOs |
| Report | 25 | Architecture diagram, timing analysis, clear writing |
| Presentation | 15 | Technical depth, Q&A readiness, even distribution |
| **Bonuses** | **+10 max** | Multi-provider failover, cost telemetry, CI, tracing, Web UI, rate limiter, multi-stage Docker |

### Automatic deductions to avoid
- Hard-coded API keys → **−10 pts**
- Non-buildable Dockerfile → **−5 pts**
- Smoke tests broken → **−5 pts**
- Modifying `ai/` → **−5 pts**
- Tests that hit network → **−5 pts**
- Severe commit imbalance → **−5 pts**
- TODOs in final code → **−3 pts**

---

## 2. Architecture Decisions

### 2.1 Storage: SQLite (dev/test) + PostgreSQL (production)

**Decision:** Use a repository abstraction with two concrete implementations:
- `SQLiteRepository` — zero-dependency, used for all tests and local development
- `PostgreSQLRepository` — `asyncpg`-backed, used in production Docker

**Rationale:** Tests must run offline without Docker. The abstract base class ensures both implementations are interchangeable. FastAPI uses dependency injection (`Depends(get_repo)`) so tests can swap the implementation trivially.

**Embedding storage:** Embeddings stored as JSON arrays in the database (portable, no `pgvector` extension required). Loaded as `np.ndarray` on read. This avoids PostgreSQL extension dependencies while remaining functionally complete.

### 2.2 Async-first design

The entire service layer is `async`. Every `ai.*` call is wrapped in `asyncio.to_thread()` because the provider SDKs are synchronous. This keeps the FastAPI event loop unblocked.

```
HTTP request → FastAPI (async) → service layer (async) → asyncio.to_thread() → ai.* (sync)
                                                                              → repository (async)
```

### 2.3 Dependency injection throughout

```python
# In api.py:
async def post_lost(file: UploadFile, repo: Repository = Depends(get_repo)):
    ...

# In tests:
app.dependency_overrides[get_repo] = lambda: FakeRepository()
```

This pattern eliminates the need for any monkey-patching in tests and makes every component independently testable.

### 2.4 Registration flow (the core workflow)

```
User uploads image + text
       ↓
[validate] MIME type, file size, text length
       ↓
[save] UUID-named image to filesystem
       ↓
[describe] asyncio.to_thread(ai.describe_item, image_path, user_text)  ← retried
       ↓
[embed] asyncio.to_thread(ai.embed, description.to_search_text())       ← cached + retried
       ↓
[persist] INSERT INTO items (status, filename, vlm_description, embedding, ...)
       ↓
Return Item with id, description, created_at
```

### 2.5 Matching flow

```
GET /items/{id}/matches?k=5
       ↓
[load] Fetch item by id → get its embedding vector
       ↓
[load] Fetch all items of OPPOSITE status + their embeddings
       ↓
[rank] ai.top_k(item.embedding, [candidate.embedding for candidate in pool])
       ↓
[enrich] Populate MatchRecord.reason with overlapping colors/marks from ItemDescription
       ↓
Return list[MatchRecord] sorted by score desc
```

### 2.6 Concurrency model

Batch registration (e.g. `POST /items/batch-lost`) processes multiple images concurrently using `asyncio.gather` bounded by a semaphore. The semaphore limit is driven by `SEMAPHORE_LIMIT` env var.

```python
sem = asyncio.Semaphore(settings.SEMAPHORE_LIMIT)

async def register_one(file):
    async with sem:
        return await _do_register(file)

results = await asyncio.gather(*[register_one(f) for f in files], return_exceptions=True)
```

### 2.7 Retry strategy

Every `ai.*` call in the service layer uses `tenacity` with:
- 3 attempts
- Exponential backoff: wait 1s → 2s → 4s
- Jitter to avoid thundering herd
- Retries on `ProviderError` and `asyncio.TimeoutError`
- Per-call timeout: 30 seconds (configurable via `AI_CALL_TIMEOUT_S`)

### 2.8 No naked dictionaries across module boundaries

Every value crossing a module boundary is a Pydantic model or dataclass. The `vlm_description` stored in the DB is serialized from `ItemDescription.model_dump()` and deserialized back to `ItemDescription` on read.

---

## 3. Technology Stack

### Core dependencies

| Package | Version | Purpose |
|---|---|---|
| `fastapi` | `>=0.104.0` | HTTP API (Pydantic v2 compatible) |
| `uvicorn[standard]` | `>=0.24.0` | ASGI server |
| `pydantic` | `>=2.5.2` | Data validation |
| `pydantic-settings` | `>=2.1.0` | Env-var typed settings |
| `python-multipart` | `>=0.0.6` | FastAPI file uploads |
| `numpy` | `>=1.26.2` | Embedding operations |
| `tenacity` | `>=8.2.2` | Retry decorator |
| `aiosqlite` | `>=0.19.0` | Async SQLite (dev + tests) |
| `asyncpg` | `>=0.29.0` | Async PostgreSQL (production) |
| `httpx` | `>=0.25.0` | Async HTTP + `AsyncClient` for FastAPI tests |
| `python-dotenv` | `>=1.0.0` | `.env` loading |

### AI provider dependencies (in `requirements-ai.txt`, kept separate)

| Package | Purpose |
|---|---|
| `anthropic` | Claude VLM |
| `openai` | OpenAI VLM + embeddings |
| `google-genai` | Gemini VLM + embeddings |

### Development / test dependencies (in `requirements-dev.txt`)

| Package | Purpose |
|---|---|
| `pytest` | Test runner |
| `pytest-asyncio` | Async test support |
| `pytest-cov` | Coverage |
| `respx` | Mock `httpx` requests |
| `ruff` | Linter |
| `mypy` | Type checker |

### Bonus feature dependencies

| Package | Purpose | Bonus |
|---|---|---|
| `opentelemetry-api` + `opentelemetry-sdk` | Distributed tracing | +2 |
| `opentelemetry-exporter-otlp` | OTLP export to Jaeger | +2 |
| `streamlit` | Web UI | +2 |

---

## 4. Final Folder Structure

```
AI Academy Final/
│
├── ai/                                    # PROVIDED — do not modify
│   ├── __init__.py
│   ├── schemas.py
│   ├── vlm.py
│   ├── embedding.py
│   ├── similarity.py
│   └── providers/
│       ├── base.py
│       ├── factory.py
│       ├── anthropic.py
│       ├── openai.py
│       └── google.py
│
├── src/                                   # SE LAYER — we build this
│   ├── __init__.py
│   ├── config.py                          # pydantic-settings, all env vars
│   ├── models.py                          # Item, MatchRecord, request/response schemas
│   ├── api.py                             # FastAPI app: 4 endpoints + health
│   ├── cli.py                             # CLI: 4 commands + cost-report (bonus)
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── ai_service.py                  # retries, caching, logging around ai.*
│   │   └── cost_meter.py                  # BONUS: per-call cost tracking
│   │
│   ├── core/
│   │   ├── __init__.py
│   │   ├── matcher.py                     # matching business logic
│   │   └── failover.py                    # BONUS: FailoverVLM, FailoverEmbedder
│   │
│   ├── concurrency/
│   │   ├── __init__.py
│   │   ├── pipeline.py                    # semaphore-bounded asyncio.gather
│   │   └── rate_limiter.py                # BONUS: TokenBudget class
│   │
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── base.py                        # AbstractRepository (ABC)
│   │   ├── repository.py                  # PostgreSQL implementation (asyncpg)
│   │   └── sqlite_repo.py                 # SQLite implementation (aiosqlite)
│   │
│   └── tracing.py                         # BONUS: OpenTelemetry setup + decorators
│
├── tests/
│   ├── conftest.py                        # Root conftest: sys.path, FakeVLM, FakeEmbedder, fixtures
│   ├── test_ai_service.py                 # retry behavior, cache hits, timeout handling
│   ├── test_repository.py                 # insert/get/list with in-memory SQLite
│   ├── test_api.py                        # all 4 endpoints via TestClient (no real DB/AI)
│   ├── test_matcher.py                    # find_matches correctness and ranking
│   ├── test_pipeline.py                   # semaphore bounds, gather degrades gracefully
│   ├── test_failover.py                   # BONUS: failover routes to secondary
│   ├── test_cost_meter.py                 # BONUS: cost accumulation and report
│   └── test_rate_limiter.py               # BONUS: budget exhaustion and back-off
│
├── topic-1-lost-and-found/                # PROVIDED
│   ├── ai/                                # original ai/ package location
│   ├── tests/
│   │   ├── conftest.py                    # FakeVLM, FakeEmbedder, sample_image
│   │   └── test_ai_smoke.py               # 30 contract tests — must not break
│   ├── data/
│   │   ├── lost/                          # 5 sample PNGs
│   │   └── found/                         # 7 sample PNGs
│   └── demo_ai.py
│
├── scripts/
│   ├── demo.py                            # end-to-end demo using all 12 sample images
│   └── bench.py                           # sequential vs concurrent timing benchmark
│
├── ui/
│   └── app.py                             # BONUS: Streamlit web UI
│
├── report/
│   └── report.tex                         # filled from templates/REPORT_TEMPLATE.tex
│
├── slides/
│   └── slides.tex                         # filled from templates/SLIDES_TEMPLATE.tex
│
├── artefacts/
│   ├── demo_run.log                       # captured output of demo.py
│   └── bench_results.txt                  # captured output of bench.py
│
├── .github/
│   └── workflows/
│       └── ci.yml                         # BONUS: GitHub Actions CI
│
├── docs/
│   └── architecture.md                    # architecture diagram (ASCII + Mermaid)
│
├── data/
│   ├── images/                            # runtime image storage (gitignored)
│   └── lost/ + found/                     # copied from topic-1-lost-and-found/data/
│
├── Dockerfile                             # BONUS: multi-stage build
├── .dockerignore
├── docker-compose.yml                     # postgres + app (for production demo)
├── requirements.txt                       # pinned runtime deps
├── requirements-ai.txt                    # provider SDKs (optional, for live calls)
├── requirements-dev.txt                   # test/lint tools
├── .env.example                           # all vars documented, no real values
├── .gitignore                             # includes .env, __pycache__, data/images/
├── README.md                              # complete: setup, env, API, CLI, bench, docker
├── PLAN.md                                # this file
└── templates/                             # PROVIDED templates (unchanged)
    ├── CONTRIBUTION_STATEMENT.md
    ├── REPORT_TEMPLATE.tex / .pdf
    ├── SLIDES_TEMPLATE.tex / .pdf
    ├── STUDENT_README_TEMPLATE.md
    └── Dockerfile.template
```

---

## 5. Data Models & Contracts

### 5.1 Database schema (items table)

```sql
CREATE TABLE IF NOT EXISTS items (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,   -- or SERIAL in PostgreSQL
    status        TEXT NOT NULL CHECK (status IN ('lost', 'found')),
    filename      TEXT NOT NULL,            -- UUID-based safe filename (stored relative to IMAGES_DIR)
    original_name TEXT,                     -- original user filename, for display only
    user_text     TEXT,
    vlm_description TEXT,                   -- JSON-serialized ItemDescription
    embedding     TEXT,                     -- JSON-serialized list[float]
    created_at    TEXT NOT NULL             -- ISO-8601 UTC timestamp
);

CREATE INDEX IF NOT EXISTS idx_items_status ON items (status);
```

### 5.2 Pydantic models (`src/models.py`)

```
# Storage model
Item:
  id: int | None
  status: Literal["lost", "found"]
  filename: str
  original_name: str | None
  user_text: str | None
  vlm_description: dict | None     (serialized ItemDescription)
  embedding: list[float] | None
  created_at: datetime | None

# API request models
RegisterItemRequest:
  user_text: str | None = None      (form field alongside file upload)

# API response models
ItemResponse:
  id: int
  status: str
  original_name: str | None
  user_text: str | None
  vlm_description: ItemDescription | None
  created_at: datetime

MatchResponse:
  candidate_id: int
  score: float
  reason: str
  candidate: ItemResponse | None   (optional: include full candidate data)

MatchListResponse:
  query_id: int
  matches: list[MatchResponse]
  count: int

ItemListResponse:
  items: list[ItemResponse]
  count: int
  status_filter: str | None
```

### 5.3 HTTP API surface

| Method | Path | Request | Response | Notes |
|---|---|---|---|---|
| `POST` | `/items/lost` | `multipart/form-data`: `file` (image) + `user_text` (optional str) | `ItemResponse` (201) | Full registration pipeline |
| `POST` | `/items/found` | same | `ItemResponse` (201) | |
| `GET` | `/items/{id}/matches` | query: `k=3` | `MatchListResponse` (200) | Matches against opposite pool |
| `GET` | `/items` | query: `status=lost\|found\|all` | `ItemListResponse` (200) | |
| `GET` | `/health` | — | `{"status": "ok", "db": "ok"}` | Checks DB connectivity |
| `POST` | `/items/batch-lost` | `multipart/form-data`: multiple files + `user_text` | `list[ItemResponse]` (201) | Concurrent batch |
| `POST` | `/items/batch-found` | same | same | |

### 5.4 CLI command surface

| Command | Arguments | Description |
|---|---|---|
| `register-lost` | `image` + `--text TEXT` | Register a lost item |
| `register-found` | `image` + `--text TEXT` | Register a found item |
| `search-matches` | `--id ID` + `--k N` | Print top-k matches for an item |
| `list` | `--status lost\|found\|all` | List registered items |
| `cost-report` | `--since 24h\|7d\|all` | BONUS: print cost summary |

---

## 6. Implementation Phases

Each phase is self-contained and testable before moving to the next.

---

### Phase 0 — Foundation (do this first, everything depends on it)

**Goal:** Clean project foundation. Every import works, config loads, no crashes on startup.

#### 0.1 Fix `requirements.txt`

Replace the current file entirely with pinned, Pydantic-v2-compatible versions:

```
# Core runtime
fastapi==0.104.1
uvicorn[standard]==0.24.0
pydantic==2.5.2
pydantic-settings==2.1.0
python-multipart==0.0.6
numpy==1.26.2
tenacity==8.2.2
python-dotenv==1.0.0

# Async storage
asyncpg==0.29.0
aiosqlite==0.19.0

# HTTP client (for tests and async calls)
httpx==0.25.2

# Testing
pytest==7.4.3
pytest-asyncio==0.23.2
pytest-cov==4.1.0

# Bonus: OpenTelemetry
opentelemetry-api==1.21.0
opentelemetry-sdk==1.21.0
opentelemetry-exporter-otlp==1.21.0

# Bonus: Web UI
streamlit==1.28.2
```

Create `requirements-ai.txt`:
```
anthropic>=0.20.0
openai>=1.10.0
google-genai>=0.3.0
```

Create `requirements-dev.txt`:
```
ruff==0.1.6
mypy==1.7.0
```

#### 0.2 Fix `src/config.py`

Complete rewrite with all needed settings:

```python
from __future__ import annotations
import logging
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Image storage
    IMAGES_DIR: str = Field("data/images", description="Filesystem path for image blobs")
    MAX_IMAGE_BYTES: int = Field(5 * 1024 * 1024, description="Max upload size (bytes)")

    # Database
    DATABASE_URL: str = Field("sqlite+aiosqlite:///./dev.db", description="DB DSN")

    # AI providers
    LLM_PROVIDER: str = Field("anthropic", description="anthropic | openai | gemini")
    LLM_MODEL: str = Field("claude-sonnet-4-6")
    ANTHROPIC_API_KEY: str | None = Field(None)
    OPENAI_API_KEY: str | None = Field(None)
    GOOGLE_API_KEY: str | None = Field(None)
    EMBEDDING_PROVIDER: str = Field("openai", description="openai | gemini")
    EMBEDDING_MODEL: str = Field("text-embedding-3-small")

    # Concurrency & rate limiting
    SEMAPHORE_LIMIT: int = Field(10, description="Max concurrent AI calls")
    AI_CALL_TIMEOUT_S: float = Field(30.0, description="Timeout per AI call (seconds)")

    # Observability
    LOG_LEVEL: str = Field("INFO")
    ENABLE_TRACING: bool = Field(False, description="Enable OpenTelemetry tracing")
    OTLP_ENDPOINT: str = Field("http://localhost:4317", description="OTLP exporter endpoint")

    # Cost telemetry (bonus)
    COST_LOG_PATH: str = Field("artefacts/cost.jsonl", description="Append-only cost log")

settings = Settings()

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
```

#### 0.3 Complete `.env.example`

```bash
# AI providers — choose one VLM and one embedder
LLM_PROVIDER=anthropic
LLM_MODEL=claude-sonnet-4-6
ANTHROPIC_API_KEY=          # sk-ant-...

# Embeddings (Anthropic has no embedding API; pair Claude with OpenAI or Gemini)
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=text-embedding-3-small
OPENAI_API_KEY=             # sk-...

# Optional alternate providers
GOOGLE_API_KEY=             # AIza...

# Storage
DATABASE_URL=sqlite+aiosqlite:///./dev.db
# DATABASE_URL=postgresql://user:pass@localhost:5432/lostfound   ← for production
IMAGES_DIR=data/images
MAX_IMAGE_BYTES=5242880

# Concurrency
SEMAPHORE_LIMIT=10
AI_CALL_TIMEOUT_S=30.0

# Observability
LOG_LEVEL=INFO
ENABLE_TRACING=false
OTLP_ENDPOINT=http://localhost:4317

# Cost telemetry (bonus)
COST_LOG_PATH=artefacts/cost.jsonl
```

#### 0.4 Create root `conftest.py`

This is critical — without it, `from ai import ...` fails in `tests/`:

```python
# conftest.py (root)
import sys
from pathlib import Path

# Make 'ai' importable from project root
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "topic-1-lost-and-found"))

# Re-export provided fixtures so tests/ can use them without duplication
from topic_1_lost_and_found.tests.conftest import (   # noqa: F401
    FakeVLM, FakeEmbedder, fake_vlm, fake_embedder, sample_image
)
```

> Note: import path depends on how the provided module is structured. Adjust accordingly.

#### 0.5 Update `src/models.py`

Add all request/response models documented in §5.2 above.

#### 0.6 Verify `.gitignore`

Ensure these are present:
```
.env
data/images/
dev.db
__pycache__/
*.pyc
.venv/
artefacts/*.log
artefacts/*.jsonl
```

**Phase 0 gate:** `python -c "from src.config import settings; print(settings)"` works without errors.

---

### Phase 1 — Storage Layer

**Goal:** A fully working repository that can insert, retrieve, and list items with real IDs.

#### 1.1 Abstract base class `src/storage/base.py`

```python
from abc import ABC, abstractmethod
from src.models import Item
import numpy as np

class AbstractRepository(ABC):
    @abstractmethod
    async def initialize(self) -> None: ...

    @abstractmethod
    async def insert_item(self, item: Item) -> Item: ...

    @abstractmethod
    async def get_item(self, item_id: int) -> Item | None: ...

    @abstractmethod
    async def list_items(self, status: str | None = None) -> list[Item]: ...

    @abstractmethod
    async def get_embeddings_by_status(self, status: str) -> list[tuple[int, np.ndarray]]: ...

    @abstractmethod
    def save_image(self, data: bytes, original_name: str) -> str: ...

    @abstractmethod
    async def close(self) -> None: ...
```

#### 1.2 SQLite implementation `src/storage/sqlite_repo.py`

- Uses `aiosqlite`
- `initialize()` runs `CREATE TABLE IF NOT EXISTS` on first call
- `insert_item()` does a real INSERT, returns item with assigned auto-increment id
- `get_item(id)` returns deserialized Item including `vlm_description` and `embedding`
- `list_items(status)` supports `None` (all), `"lost"`, `"found"`
- `get_embeddings_by_status(status)` returns `[(id, np.array(embedding)), ...]`
- `save_image(data, original_name)` writes bytes to `UUID + suffix` path, returns relative path — **UUID-based to prevent path traversal**

```python
import uuid
from pathlib import Path

def save_image(self, data: bytes, original_name: str) -> str:
    suffix = Path(original_name).suffix.lower() or ".png"
    safe_name = uuid.uuid4().hex + suffix
    dest = (Path(settings.IMAGES_DIR) / safe_name).resolve()
    storage_root = Path(settings.IMAGES_DIR).resolve()
    assert str(dest).startswith(str(storage_root)), "path escapes storage dir"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return safe_name
```

#### 1.3 PostgreSQL implementation `src/storage/repository.py`

- Uses `asyncpg` connection pool
- `initialize()` creates pool + runs schema DDL
- All queries use parameterized statements (no SQL injection)
- `SERIAL` primary key instead of `AUTOINCREMENT`
- Same interface as SQLiteRepository — drop-in replacement

#### 1.4 Factory function

```python
# src/storage/__init__.py
def get_repo() -> AbstractRepository:
    if settings.DATABASE_URL.startswith("sqlite"):
        return SQLiteRepository(settings.DATABASE_URL)
    return PostgreSQLRepository(settings.DATABASE_URL)
```

**Phase 1 gate:** `pytest tests/test_repository.py -v` passes (all CRUD operations verified against in-memory SQLite).

---

### Phase 2 — Service Layer

**Goal:** Every call to `ai.*` is resilient, logged, cached, and timed.

#### 2.1 Complete `src/services/ai_service.py`

Key elements:

**Retry decorator:**
```python
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from ai.providers.base import ProviderError

_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((ProviderError, TimeoutError)),
    reraise=True,
)
```

**Per-call timeout:**
```python
import asyncio

async def describe_item_async(image_path: str, user_text: str, *, vlm=None) -> ItemDescription:
    return await asyncio.wait_for(
        asyncio.to_thread(describe_item, image_path, user_text, vlm=vlm),
        timeout=settings.AI_CALL_TIMEOUT_S,
    )
```

**LRU cache for embeddings (text → vector):**
```python
from functools import lru_cache

@lru_cache(maxsize=2048)
def _embed_cached_sync(text: str) -> tuple:     # tuple so it's hashable/cacheable
    vec = embed(text)
    return tuple(vec.tolist())

async def embed_async(text: str, *, embedder=None) -> np.ndarray:
    if not text.strip():
        raise ValueError("Cannot embed empty text")
    cached = _embed_cached_sync(text)
    return np.array(cached, dtype=np.float32)
```

**Structured logging throughout:**
```python
log.info("describe_item.start", extra={"image": image_path, "text_len": len(user_text)})
log.info("describe_item.ok", extra={"class": result.object_class, "conf": result.confidence})
log.warning("describe_item.retry", extra={"attempt": attempt, "error": str(e)})
```

#### 2.2 Wire `src/core/matcher.py`

```python
async def find_matches(
    item: Item,
    repo: AbstractRepository,
    k: int = 3,
) -> list[MatchRecord]:
    if item.embedding is None:
        raise ValueError("Item has no embedding — register first")
    
    opposite = "found" if item.status == "lost" else "lost"
    candidates = await repo.get_embeddings_by_status(opposite)
    
    if not candidates:
        return []
    
    candidate_ids = [cid for cid, _ in candidates]
    candidate_vecs = [vec for _, vec in candidates]
    query_vec = np.array(item.embedding, dtype=np.float32)
    
    raw = top_k(query_vec, candidate_vecs, k=k)
    
    return [
        MatchRecord(
            candidate_id=candidate_ids[r.candidate_id],
            score=r.score,
            reason=_build_reason(item, r),
        )
        for r in raw
    ]

def _build_reason(query_item: Item, match: MatchResult) -> str:
    # Enrich reason with overlapping colors/object class from ItemDescription
    ...
```

**Phase 2 gate:** `pytest tests/test_ai_service.py tests/test_matcher.py -v` passes.

---

### Phase 3 — HTTP API

**Goal:** All 4 required endpoints + batch endpoints working end-to-end.

#### 3.1 Complete `src/api.py`

Structure:

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI, File, Form, UploadFile, HTTPException, Depends, Query
from src.storage.base import AbstractRepository
from src.storage import get_repo

@asynccontextmanager
async def lifespan(app: FastAPI):
    repo = get_repo()
    await repo.initialize()        # create tables on startup
    app.state.repo = repo
    yield
    await repo.close()

app = FastAPI(title="Smart Lost & Found API", lifespan=lifespan)

def _get_repo() -> AbstractRepository:
    return app.state.repo
```

**POST /items/lost and /items/found:**
1. Validate `content_type in {"image/png", "image/jpeg"}`
2. Read bytes; validate `len(data) <= settings.MAX_IMAGE_BYTES`
3. `filename = repo.save_image(data, file.filename)`
4. `description = await describe_item_async(filepath, user_text or "")`  ← retried
5. `embedding = await embed_async(description.to_search_text())`  ← cached
6. `item = Item(status="lost", filename=filename, ...)`
7. `saved = await repo.insert_item(item)`
8. Return `ItemResponse` with 201 status code

**GET /items/{id}/matches:**
- Fetch item; 404 if not found
- Call `find_matches(item, repo, k=k)`
- Return `MatchListResponse`

**GET /items:**
- Call `repo.list_items(status=status_filter)`
- Return `ItemListResponse`

**Input validation middleware:**
```python
# Validation helper (not a bare except)
def _validate_image(file: UploadFile, data: bytes) -> None:
    if file.content_type not in {"image/png", "image/jpeg", "image/jpg"}:
        raise HTTPException(400, detail=f"Unsupported type: {file.content_type}")
    if len(data) > settings.MAX_IMAGE_BYTES:
        raise HTTPException(413, detail=f"File too large (max {settings.MAX_IMAGE_BYTES} bytes)")
```

**Global exception handler:**
```python
from ai.providers.base import ProviderError

@app.exception_handler(ProviderError)
async def provider_error_handler(request, exc):
    log.error("provider_error", extra={"error": str(exc)})
    return JSONResponse(status_code=502, content={"detail": "AI provider error", "message": str(exc)})
```

**Phase 3 gate:** `pytest tests/test_api.py -v` passes. Manual `curl` test of all 4 endpoints works.

---

### Phase 4 — CLI

**Goal:** All 4 CLI commands share the same service layer as the API (no logic duplication).

#### 4.1 Complete `src/cli.py`

Use `argparse` (already started) or migrate to `click` (cleaner, but adds a dependency — argparse is fine).

Key design: CLI commands call the same `async` service functions as the API, run via `asyncio.run()`.

```python
def register_lost(args):
    asyncio.run(_async_register_lost(args))

async def _async_register_lost(args):
    repo = get_repo()
    await repo.initialize()
    try:
        data = Path(args.image).read_bytes()
        filename = repo.save_image(data, Path(args.image).name)
        image_path = str(Path(settings.IMAGES_DIR) / filename)
        description = await describe_item_async(image_path, args.text or "")
        embedding = await embed_async(description.to_search_text())
        item = Item(status="lost", filename=filename, ...)
        saved = await repo.insert_item(item)
        log.info("registered_item", extra={"id": saved.id, "class": description.object_class})
        print(f"Registered: id={saved.id}  class={description.object_class}")
    finally:
        await repo.close()
```

Note: `print()` to stdout is allowed for CLI user-facing output. Use `log.*` for diagnostics.

**Phase 4 gate:** `python -m src.cli register-lost data/lost/backpack_navy.png --text "navy backpack"` runs without error in offline mode (using FakeVLM override).

---

### Phase 5 — Concurrency & Benchmark

**Goal:** Measurable speedup from parallel processing; benchmark script produces a table.

#### 5.1 Complete `src/concurrency/pipeline.py`

```python
async def register_batch(
    files: list[tuple[bytes, str]],     # (image_bytes, original_name)
    status: str,
    user_texts: list[str | None],
    repo: AbstractRepository,
) -> list[Item | Exception]:
    sem = asyncio.Semaphore(settings.SEMAPHORE_LIMIT)
    
    async def _one(data: bytes, name: str, text: str | None) -> Item:
        async with sem:
            return await _register_single(data, name, text, status, repo)
    
    tasks = [_one(d, n, t) for (d, n), t in zip(files, user_texts)]
    return await asyncio.gather(*tasks, return_exceptions=True)
```

#### 5.2 Write `scripts/bench.py`

```python
"""Sequential vs concurrent benchmark.

Usage:
    python scripts/bench.py --n 12 --mode both
    python scripts/bench.py --n 12 --mode sequential
    python scripts/bench.py --n 12 --mode concurrent
"""
```

The script:
1. Loads all images from `data/lost/` + `data/found/` (up to N total)
2. Registers them SEQUENTIALLY (one by one) — records total wall time
3. Clears the DB
4. Registers them CONCURRENTLY (via `register_batch`) — records total wall time
5. Prints a comparison table
6. Identifies the bottleneck (provider latency, rate limits, DB writes)

Example output:
```
Workload: 12 images, FakeVLM (offline mode)
┌────────────┬───────────┬─────────────────────────┬─────────┐
│ Mode       │ N         │ Wall time               │ Speedup │
├────────────┼───────────┼─────────────────────────┼─────────┤
│ Sequential │ 12        │ 24.3 s                  │ 1.0×    │
│ Concurrent │ 12        │  5.1 s  (sem=10)        │ 4.8×    │
└────────────┴───────────┴─────────────────────────┴─────────┘
Bottleneck: provider network RTT (mock eliminated it — real run expect ~3× speedup)
```

**Phase 5 gate:** `python scripts/bench.py --n 12 --mode both` runs and prints a table. Numbers are captured in `artefacts/bench_results.txt` and pasted into the README.

---

### Phase 6 — Robustness & Error Handling

**Goal:** System fails gracefully, logs clearly, and never leaks a stack trace to the user.

#### 6.1 Failure mode audit

Every entry point (CLI command, API endpoint) must handle:
- `ProviderError` — AI call failed (after retries) → HTTP 502 / CLI error message
- `asyncio.TimeoutError` — AI call timed out → HTTP 504 / CLI error message
- `FileNotFoundError` — image path doesn't exist (CLI) → CLI error message
- `ValidationError` — bad input → HTTP 400 / CLI error message
- DB connection failure → HTTP 503 / CLI error message

#### 6.2 Failure injection test

Write `tests/test_failures.py`:
- Monkeypatch `ai.describe_item` to raise `ProviderError` on first 2 calls → verify retry fires 2 times, succeeds on 3rd
- Monkeypatch `ai.describe_item` to always raise → verify HTTP 502 returned
- Monkeypatch `ai.describe_item` to sleep > timeout → verify `asyncio.TimeoutError` caught
- Upload a file > `MAX_IMAGE_BYTES` → verify HTTP 413
- Upload a PDF → verify HTTP 400

#### 6.3 Coverage gate

Run `pytest --cov=src --cov-report=term-missing --cov-fail-under=60`. Fix gaps until gate passes.

**Phase 6 gate:** `pytest --cov=src --cov-fail-under=60` exits 0.

---

### Phase 7 — Bonus Features

These are implemented after the core is solid. In priority order (highest points first):

#### 7.1 Multi-provider failover (+3 pts) — `src/core/failover.py`

```python
class FailoverVLM(VLMProvider):
    def __init__(self, providers: list[VLMProvider]) -> None:
        self._providers = providers

    def describe(self, image_path: str, prompt: str, *, json_schema=None) -> str:
        last_error: Exception | None = None
        for i, p in enumerate(self._providers):
            try:
                return p.describe(image_path, prompt, json_schema=json_schema)
            except ProviderError as e:
                log.warning("failover.primary_failed", extra={"index": i, "error": str(e)})
                last_error = e
        raise ProviderError(f"all providers failed; last: {last_error}")

class FailoverEmbedder(EmbeddingProvider):
    # same pattern
```

Integration: `ai_service.py` constructs a failover provider if `SECONDARY_LLM_PROVIDER` env var is set.

Test: `tests/test_failover.py` — primary mocked to raise, secondary FakeVLM returns valid result.

#### 7.2 Cost telemetry (+2 pts) — `src/services/cost_meter.py`

```python
PRICING: dict[tuple[str, str], tuple[float, float]] = {
    ("anthropic", "claude-sonnet-4-6"):   (0.003, 0.015),
    ("openai", "gpt-4o-mini"):            (0.00015, 0.0006),
    ("openai", "text-embedding-3-small"): (0.00002, 0.0),
    ("gemini", "gemini-2.0-flash"):       (0.000075, 0.0003),
}

@dataclass
class CostEvent:
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    dollars: float
    timestamp: str

class CostMeter:
    def __init__(self, log_path: str): ...
    def record(self, provider, model, prompt_t, completion_t) -> None: ...   # appends JSONL
    def report(self, since: timedelta | None = None) -> str: ...              # prints table
```

CLI command `cost-report --since 24h` calls `CostMeter.report()`.

#### 7.3 OpenTelemetry tracing (+2 pts) — `src/tracing.py`

```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

def setup_tracing() -> trace.Tracer:
    provider = TracerProvider()
    if settings.ENABLE_TRACING:
        exporter = OTLPSpanExporter(endpoint=settings.OTLP_ENDPOINT)
        provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return trace.get_tracer("lostfound")

tracer = setup_tracing()
```

Decorator applied to `describe_item_async`, `embed_async`, and repository methods:
```python
async def describe_item_async(image_path, user_text, *, vlm=None):
    with tracer.start_as_current_span("ai.describe_item") as span:
        span.set_attribute("provider", settings.LLM_PROVIDER)
        span.set_attribute("model", settings.LLM_MODEL)
        try:
            result = await ...
            span.set_attribute("status", "ok")
            return result
        except Exception as e:
            span.set_attribute("status", "error")
            span.record_exception(e)
            raise
```

#### 7.4 Token-aware rate limiter (+2 pts) — `src/concurrency/rate_limiter.py`

```python
class TokenBudget:
    def __init__(self, tokens_per_minute: int) -> None:
        self.tpm = tokens_per_minute
        self._events: deque[tuple[float, int]] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self, estimated_tokens: int) -> None:
        while True:
            async with self._lock:
                now = time.monotonic()
                while self._events and self._events[0][0] < now - 60:
                    self._events.popleft()
                used = sum(t for _, t in self._events)
                if used + estimated_tokens <= self.tpm:
                    self._events.append((now, estimated_tokens))
                    return
                wait = 60 - (now - self._events[0][0]) if self._events else 0.5
            await asyncio.sleep(max(wait, 0.1))
```

Integration: `ai_service.py` calls `budget.acquire(estimated_tokens)` before each provider call.

#### 7.5 Streamlit Web UI (+2 pts) — `ui/app.py`

A clean single-file UI:
- Page 1: **Register Lost/Found** — file uploader + text field → calls service layer → shows description + id
- Page 2: **Find Matches** — enter item id + k → shows match cards with scores and reasons
- Page 3: **Browse Items** — table view of all registered items with status filter

The UI imports from `src.*` directly — no duplicate business logic.

#### 7.6 GitHub Actions CI (+2 pts) — `.github/workflows/ci.yml`

```yaml
name: CI
on: [push, pull_request]
jobs:
  ci:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12", cache: pip }
      - run: pip install -r requirements.txt -r requirements-dev.txt
      - name: Lint
        run: ruff check src/ tests/
      - name: Type check
        run: mypy src/ --ignore-missing-imports
      - name: Test + coverage
        run: pytest --cov=src --cov-fail-under=60 --cov-report=term-missing
      - name: Docker build
        run: docker build --platform linux/amd64 -t finalproj .
```

---

### Phase 8 — Docker

**Goal:** Multi-stage build, small image, builds from clean clone.

#### 8.1 Multi-stage `Dockerfile` (+1 pt)

```dockerfile
# ---- Build stage ----
FROM python:3.12-slim AS builder
WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ---- Runtime stage ----
FROM python:3.12-slim
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
COPY . .
RUN useradd --create-home --shell /bin/bash appuser \
    && chown -R appuser:appuser /app
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health').raise_for_status()"
CMD ["uvicorn", "src.api:app", "--host", "0.0.0.0", "--port", "8000"]
```

#### 8.2 `.dockerignore`

```
.git
.venv
__pycache__
*.pyc
*.pyo
.env
dev.db
data/images/
artefacts/
report/*.pdf
slides/*.pdf
```

#### 8.3 `docker-compose.yml` (for PostgreSQL production demo)

```yaml
version: "3.9"
services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: lostfound
      POSTGRES_USER: lf
      POSTGRES_PASSWORD: lf_pass
    ports: ["5432:5432"]
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "lf"]
      interval: 5s

  api:
    build: .
    ports: ["8000:8000"]
    env_file: .env
    environment:
      DATABASE_URL: postgresql://lf:lf_pass@db:5432/lostfound
    depends_on:
      db: { condition: service_healthy }
```

**Phase 8 gate:** `docker build --platform linux/amd64 -t finalproj .` exits 0 on a clean clone.

---

### Phase 9 — Documentation

#### 9.1 Architecture diagram (`docs/architecture.md`)

```
┌──────────────────────────────────────────────────────────┐
│                     Entry Points                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐  │
│  │  FastAPI    │  │   CLI       │  │  Streamlit UI   │  │
│  │  (api.py)   │  │  (cli.py)   │  │  (ui/app.py)    │  │
│  └──────┬──────┘  └──────┬──────┘  └────────┬────────┘  │
└─────────┼────────────────┼──────────────────┼───────────┘
          │                │                  │
          └────────────────┼──────────────────┘
                           │ depends on
          ┌────────────────▼──────────────────────────────┐
          │              Service Layer                     │
          │  ┌──────────────────┐  ┌─────────────────┐   │
          │  │  ai_service.py   │  │   matcher.py     │   │
          │  │ (retry, cache,   │  │ (top_k + enrich) │   │
          │  │  logging, trace) │  └────────┬────────┘   │
          │  └────────┬─────────┘           │            │
          └───────────┼─────────────────────┼────────────┘
                      │                     │
          ┌───────────▼─────┐   ┌───────────▼────────────┐
          │   AI Module     │   │   Storage Layer         │
          │   (provided)    │   │  ┌──────────────────┐  │
          │  describe_item  │   │  │ SQLiteRepository  │  │
          │  embed          │   │  │ PostgreSQLRepo    │  │
          │  cosine, top_k  │   │  │ (filesystem imgs) │  │
          └─────────────────┘   └──────────────────────┘
          ┌─────────────────────────────────────────────┐
          │           Cross-cutting Concerns            │
          │  Retries (tenacity) · OTel Tracing         │
          │  Cost Meter · Token Budget · Semaphore     │
          └─────────────────────────────────────────────┘
```

#### 9.2 README

Fill `templates/STUDENT_README_TEMPLATE.md` with:
- Quick start (3 commands)
- Full env var table
- All curl examples for every endpoint
- `docker run` commands
- Benchmark table from `artefacts/bench_results.txt`
- Coverage badge / number
- Architecture diagram (reference `docs/architecture.md`)

#### 9.3 Report (`report/report.tex`)

Fill `templates/REPORT_TEMPLATE.tex` section by section:
- §1 Introduction: The problem, the AI module, what we built
- §2 Architecture: Why this layered design, why async, why the repository pattern
- §3 Storage: SQLite vs PostgreSQL trade-offs, why JSON embedding storage
- §4 Concurrency: The asyncio model, semaphore rationale, benchmark results with graph
- §5 Robustness: Retry strategy, timeout choices, failure mode analysis with log excerpts
- §6 Testing: What we tested, what we mocked, coverage table, offline guarantee
- §7 Bonus features: Failover design, cost telemetry results, tracing architecture
- §8 Limitations & future work
- §9 Conclusion

#### 9.4 Slides (`slides/slides.tex`)

~12 slides covering:
1. Title + team
2. Problem statement (1 slide)
3. Architecture overview (diagram)
4. AI module contract (what we were given)
5. Storage layer design decision
6. Retry + caching strategy
7. Concurrency model + benchmark graph
8. Testing approach (coverage screenshot)
9. Bonus: Failover + cost telemetry
10. Live demo screenshot (or pre-recorded)
11. Limitations
12. Q&A

---

## 7. Dependency Graph

```
Phase 0 (Foundation)
    └──► Phase 1 (Storage)
             ├──► Phase 2 (Service Layer)
             │         ├──► Phase 3 (HTTP API)
             │         │         ├──► Phase 5 (Concurrency & Bench)
             │         │         └──► Phase 4 (CLI)
             │         └──► Phase 6 (Robustness & Tests)
             │                   ├──► Phase 7 (Bonus Features)  [parallel]
             │                   └──► Phase 8 (Docker)
             │                             └──► Phase 9 (Docs & Report)
             └──► root conftest.py ──► all tests
```

**Strictly sequential:** 0 → 1 → 2 → 3  
**Can parallelize:** Phase 4 (CLI) and Phase 3 (API) share service layer, can be done in parallel by two people once Phase 2 is done.  
**Can parallelize:** Phase 7 bonus features are largely independent of each other.

---

## 8. Bonus Feature Strategy

| Bonus | Points | Effort | Priority | Dependency |
|---|---|---|---|---|
| Multi-provider failover | +3 | Medium | **#1** — highest ROI | Phase 2 done |
| Cost telemetry | +2 | Low | **#2** — adds to failover story | Phase 2 done |
| GitHub Actions CI | +2 | Low | **#3** — validates everything else | Phase 6 done |
| OpenTelemetry tracing | +2 | Medium | **#4** | Phase 2 done |
| Streamlit Web UI | +2 | Medium | **#5** | Phase 3 done |
| Token-aware rate limiter | +2 | Medium | **#6** | Phase 5 done |
| Multi-stage Dockerfile | +1 | Low | **#7** — do with Phase 8 | Phase 8 |

**Maximum achievable:** +10 pts (all 7 bonuses sum to +14, capped at +10).

**Recommended minimum bonus set for solid +8:** failover (+3) + cost telemetry (+2) + CI (+2) + multi-stage Docker (+1).

---

## 9. Testing Strategy

### Test categories and targets

| Test file | What it tests | Mocks used | Target coverage contribution |
|---|---|---|---|
| `test_repository.py` | CRUD operations, SQLite | in-memory SQLite | `storage/` → 85% |
| `test_ai_service.py` | retries, cache, timeout | `FakeVLM`, `FakeEmbedder` | `services/` → 80% |
| `test_matcher.py` | ranking correctness, reason enrichment | `FakeEmbedder` | `core/matcher.py` → 90% |
| `test_api.py` | all endpoints, validation, error codes | `TestClient`, dependency overrides | `api.py` → 75% |
| `test_pipeline.py` | semaphore bounds, gather degrades gracefully | `asyncio.sleep` | `concurrency/` → 70% |
| `test_failures.py` | retry fires, timeout caught, 413/400 returned | monkeypatch | `services/` + `api.py` → +5% |
| `test_failover.py` | failover routes to secondary | `Mock(spec=VLMProvider)` | `core/failover.py` → 90% |
| `test_cost_meter.py` | event recording, report accuracy | JSONL temp file | `services/cost_meter.py` → 85% |
| `test_rate_limiter.py` | budget exhaustion, back-off sleep | mock `asyncio.sleep` | `concurrency/rate_limiter.py` → 80% |

### Offline guarantee

All tests use `FakeVLM`, `FakeEmbedder`, or `monkeypatch` — zero network calls. Verified by: unplug network, run `pytest`, all green.

### Coverage command

```bash
pytest --cov=src --cov-report=term-missing --cov-report=html --cov-fail-under=60
```

Target: **≥70%** (exceeds the 60% minimum; provides buffer).

### Type checking

```bash
mypy src/ --ignore-missing-imports --strict
```

Fix all errors before final submission. Record result in README.

### Linting

```bash
ruff check src/ tests/ --fix
```

Zero errors on final submission.

---

## 10. Docker & Deployment Strategy

### Build verification steps

```bash
# 1. Build for the grader's platform (Linux/amd64)
docker buildx build --platform linux/amd64 -t finalproj .

# 2. Check image size
docker images finalproj

# 3. Run smoke tests inside the container
docker run --platform linux/amd64 finalproj pytest topic-1-lost-and-found/tests/test_ai_smoke.py -v

# 4. Start the API
docker run --platform linux/amd64 --env-file .env -p 8000:8000 finalproj

# 5. Test the API from host
curl http://localhost:8000/health
```

### Production deployment (PostgreSQL)

```bash
docker compose up --build
# Then hit http://localhost:8000
```

---

## 11. Documentation & Presentation Plan

### README must include

- [ ] One-sentence pitch
- [ ] Quick-start in 3 steps (clone → configure → run)
- [ ] Full environment variable table
- [ ] `curl` examples for every API endpoint (with sample responses)
- [ ] `docker build` and `docker run` commands
- [ ] Benchmark table (sequential vs concurrent)
- [ ] Coverage number
- [ ] Architecture diagram

### Report structure (from template, ~8-10 pages)

- [ ] Every `[TODO: ...]` replaced with real content
- [ ] Architecture diagram (same as in docs/)
- [ ] Timing table from bench.py
- [ ] At least one failure mode with log excerpt
- [ ] Bonus features explained with design rationale
- [ ] Self-critical limitations section

### Presentation (10 minutes + Q&A)

- [ ] Each team member owns ≥ 2 slides and can answer Q&A on their component
- [ ] Live demo OR pre-recorded video (pre-record as backup)
- [ ] Architecture diagram visible and explained
- [ ] One benchmark graph (sequential vs concurrent bars)
- [ ] One coverage screenshot

---

## 12. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `pydantic.BaseSettings` import crash | Certain | High | Fix in Phase 0.2 first |
| FastAPI 0.95 + Pydantic v2 incompatibility | Certain | High | Upgrade to FastAPI ≥ 0.104 in Phase 0.1 |
| asyncpg fails on Windows (dev machine) | Medium | Medium | Use aiosqlite for local dev; asyncpg in Docker only |
| Provider API keys not available | Low | High | Use offline mode (`FakeVLM`) for all tests; keys only for final demo |
| Smoke tests break after changes | Low | High | Run `pytest topic-1-lost-and-found/tests/test_ai_smoke.py` after every change |
| `.env` accidentally committed | Medium | High | Pre-commit hook: `git grep -E "sk-[a-zA-Z0-9_-]{20,}"` |
| Tests hit network | Medium | Medium | Add `PYTHONDONTALLOWNETWORK=1` to pytest env in CI |
| Docker build fails on grader machine | Medium | High | Always build with `--platform linux/amd64` |
| Coverage below 60% at submission | Low | Medium | Track coverage after each phase; Phase 6 gate enforces it |

---

## 13. Quality Checklist

Run these before considering the project done:

### Code quality
- [ ] `ruff check src/ tests/` — zero errors
- [ ] `mypy src/ --ignore-missing-imports` — zero errors
- [ ] `git grep -nE "TODO|FIXME|XXX" src/ tests/` — zero matches
- [ ] `git grep -n "print(" src/` — only CLI user-output prints remain (no debug prints)
- [ ] `git grep -E "sk-[a-zA-Z0-9_-]{20,}|AIza[a-zA-Z0-9_-]{20,}"` — zero matches
- [ ] `git grep -nE "except\s*:|except\s+Exception\s*:\s*pass"` — zero matches

### Tests
- [ ] `pytest topic-1-lost-and-found/tests/test_ai_smoke.py -v` — all 30 pass
- [ ] `pytest tests/ -v` — all custom tests pass
- [ ] `pytest --cov=src --cov-fail-under=60` — exits 0
- [ ] All tests pass with network cable unplugged

### Functionality
- [ ] `POST /items/lost` with a real image returns 201 + ItemResponse
- [ ] `POST /items/found` with a real image returns 201 + ItemResponse
- [ ] `GET /items/{id}/matches` returns ranked matches
- [ ] `GET /items?status=lost` returns a list
- [ ] `GET /health` returns `{"status": "ok"}`
- [ ] CLI `register-lost`, `register-found`, `search-matches`, `list` all work
- [ ] `python scripts/bench.py` produces a timing table

### Docker
- [ ] `docker buildx build --platform linux/amd64 -t finalproj .` exits 0
- [ ] Container starts and `/health` responds
- [ ] Smoke tests pass inside the container

### Documentation
- [ ] README: no template placeholders remain
- [ ] `.env.example`: all variables documented, no real values
- [ ] `requirements.txt`: every dep has a pinned version
- [ ] Report: every `[TODO: ...]` replaced
- [ ] Slides: prepared, each member owns slides, 10-min timing tested

### Final submission
- [ ] `v1.0-final` git tag on main
- [ ] `artefacts/` folder has demo run output and bench results
- [ ] Contribution statement signed by all 3 members

---

*Plan version: 1.0 | Written before implementation begins.*
