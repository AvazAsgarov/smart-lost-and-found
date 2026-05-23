# Architecture — Smart Lost & Found

## System Overview

```text
┌─────────────────────────────────────────────────────────────────────┐
│                        Entry Points                                  │
│                                                                     │
│   ┌───────────────┐   ┌───────────────┐   ┌───────────────────┐    │
│   │  FastAPI API  │   │  Streamlit UI │   │    CLI (src/cli)   │    │
│   │  src/api.py   │   │  ui/app.py    │   │  python -m src.cli│    │
│   │  :8000/docs   │   │  :8501        │   │                   │    │
│   └──────┬────────┘   └──────┬────────┘   └────────┬──────────┘    │
└──────────┼──────────────────┼────────────────────┼──────────────────┘
           │                  │                    │
           └──────────────────┼────────────────────┘
                              │ calls
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        Service Layer                                  │
│                                                                     │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │  src/services/ai_service.py                                     │ │
│  │                                                                 │ │
│  │  describe_item_async()         embed_async()                   │ │
│  │    │ rate_limiter.acquire()      │ rate_limiter.acquire()       │ │
│  │    │ asyncio.wait_for(           │ asyncio.wait_for(            │ │
│  │    │   to_thread(describe_item)) │   to_thread(embed))          │ │
│  │    │ cost_meter.record()         │ cost_meter.record()          │ │
│  │    │ @retry (tenacity)           │ @retry (tenacity)            │ │
│  └────┼────────────────────────────┼────────────────────────────┘ │
│       │                            │                               │
│  ┌────┼────────────────────────────┼────────────────────────────┐  │
│  │ src/core/matcher.py             │                             │  │
│  │  find_matches()  ←─────────────┘                             │  │
│  │    cosine similarity on embedding pool                        │  │
│  └───────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
           │                  │
           ▼                  ▼
┌──────────────────┐ ┌────────────────────────────────────────────────┐
│  ai/  (root pkg) │ │           Storage Layer                         │
│  Provided AI lib │ │                                                │
│                  │ │  src/storage/base.py  (AbstractRepository ABC) │
│  describe_item() │ │         ▲               ▲                      │
│  embed()         │ │  sqlite_repo.py    repository.py               │
│                  │ │  (aiosqlite)       (asyncpg / PostgreSQL)      │
│  VLM providers:  │ │                                                │
│   Anthropic      │ │  save_image() — UUID filename, path-escape     │
│   OpenAI         │ │  insert_item(), get_item(), list_items()       │
│   Gemini         │ │  get_embeddings_by_status()                    │
│                  │ └────────────────────────────────────────────────┘
│  Embedders:      │          │
│   OpenAI         │          ▼
│   Gemini         │ ┌────────────────────────────────────────────────┐
└──────────────────┘ │         Data Layer                              │
                     │                                                │
                     │  SQLite (dev)  /  PostgreSQL (prod)            │
                     │  data/images/  (UUID-named image files)        │
                     │  artefacts/cost.jsonl  (cost telemetry)        │
                     └────────────────────────────────────────────────┘
```

---

## Bonus Features

```text
┌──────────────────────────────────────────────────────────────────────┐
│                    Bonus Modules                                       │
│                                                                      │
│  src/core/failover.py         FailoverVLM / FailoverEmbedder         │
│  ┌────────────────────────┐   Tries providers in ranked order;       │
│  │ Primary VLM            │   on ProviderError falls through to      │
│  │ (e.g. Anthropic)       │──►│ Secondary VLM                        │
│  └────────────────────────┘   (e.g. OpenAI)                          │
│                                                                      │
│  src/concurrency/rate_limiter.py    TokenBudget                      │
│  ┌────────────────────────────────────────────────┐                  │
│  │  60-second sliding window                      │                  │
│  │  deque[(ts, tokens)] → sum → compare to TPM   │                  │
│  │  async acquire() sleeps until headroom opens  │                  │
│  └────────────────────────────────────────────────┘                  │
│                                                                      │
│  src/services/cost_meter.py    CostMeter                             │
│  ┌──────────────────────────────────────────────┐                    │
│  │  JSONL append-only log                       │                    │
│  │  provider + model + tokens → USD estimate    │                    │
│  │  python -m src.cli cost-report --since 24    │                    │
│  └──────────────────────────────────────────────┘                    │
│                                                                      │
│  src/tracing.py    OpenTelemetry                                     │
│  ┌─────────────────────────────────────────────┐                     │
│  │  @traced_ai_call  /  @traced_db_op          │                     │
│  │  OTLP → Jaeger  (ENABLE_TRACING=true)       │                     │
│  │  No-op tracer when ENABLE_TRACING=false      │                     │
│  └─────────────────────────────────────────────┘                     │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Concurrency Model

```text
HTTP request arrives
        │
        ▼
FastAPI async endpoint  (event loop thread)
        │
        ├─ asyncio.Semaphore(SEMAPHORE_LIMIT)  ← cap concurrent AI calls
        │
        ├─ TokenBudget.acquire(est_tokens)     ← respect provider TPM
        │
        ├─ asyncio.wait_for(                   ← per-call timeout
        │     asyncio.to_thread(               ← sync AI SDK → thread pool
        │       describe_item / embed
        │     ),
        │     timeout=AI_CALL_TIMEOUT_S
        │  )
        │
        │  @retry (tenacity exponential backoff)
        │
        └─ await repo.insert_item(...)         ← async DB write
```

---

## Data Flow — Item Registration

```text
User uploads image
        │
        ▼
POST /items/lost  or  POST /items/found
        │
   [1] _read_and_validate_image()
        │  check Content-Type, MAX_IMAGE_BYTES
        ▼
   [2] repo.save_image(bytes, original_name)
        │  → UUID hex + original suffix
        │  → data/images/{uuid}.jpg
        ▼
   [3] describe_item_async(stored_path, user_text)
        │  VLM → ItemDescription(object_class, colors, brand, confidence)
        ▼
   [4] embed_async(description.to_search_text())
        │  Embedding provider → float32[N] unit-normalized
        ▼
   [5] repo.insert_item(Item(...))
        │  SQL INSERT → returns Item with id
        ▼
   [6] ItemResponse.from_item(item)
        │  JSON serialized, returned to client
        ▼
   HTTP 201 Created
```

---

## Match Retrieval

```text
GET /items/{id}/matches?k=3
        │
   [1] repo.get_item(id)           ← fetch query item
        │
   [2] repo.get_embeddings_by_status(opposite)
        │  all candidate (id, vector) pairs
        │
   [3] cosine_similarity(query_vec, candidate_vecs)
        │  numpy dot product (unit-normalized → cosine = dot)
        │
   [4] top_k(scores, k=3)          ← ai.similarity module
        │
   [5] _build_reason(...)          ← enrich with shared colors/class/brand
        │
   MatchListResponse → HTTP 200
```

---

## Directory Structure

```text
AI Academy Final/
├── ai/                        Provided AI library (root-level package)
│   ├── providers/             VLM + embedding provider implementations
│   ├── schemas.py             ItemDescription dataclass + JSON schema
│   ├── similarity.py          top_k(), cosine() helpers
│   ├── vlm.py                 describe_item() entry point
│   └── embedding.py           embed() entry point
├── src/
│   ├── api.py                 FastAPI application
│   ├── cli.py                 argparse CLI
│   ├── config.py              pydantic-settings Settings
│   ├── models.py              Pydantic models (Item, MatchRecord, …)
│   ├── tracing.py             OpenTelemetry setup
│   ├── core/
│   │   ├── failover.py        FailoverVLM, FailoverEmbedder
│   │   └── matcher.py         find_matches(), _build_reason()
│   ├── services/
│   │   ├── ai_service.py      describe_item_async(), embed_async()
│   │   └── cost_meter.py      CostMeter, estimate_cost()
│   ├── storage/
│   │   ├── base.py            AbstractRepository ABC
│   │   ├── sqlite_repo.py     SQLiteRepository (aiosqlite)
│   │   └── repository.py      PostgreSQLRepository (asyncpg)
│   └── concurrency/
│       ├── pipeline.py        run_with_semaphore(), register_batch()
│       └── rate_limiter.py    TokenBudget
├── ui/
│   └── app.py                 Streamlit Web UI
├── tests/
│   ├── fakes.py               FakeVLM, FakeEmbedder (canonical location)
│   ├── test_ai_smoke.py       Provided smoke tests (grading contract)
│   ├── test_repository.py
│   ├── test_ai_service.py
│   ├── test_matcher.py
│   ├── test_api.py
│   ├── test_pipeline.py
│   ├── test_failures.py
│   ├── test_failover.py
│   ├── test_cost_meter.py
│   └── test_rate_limiter.py
├── scripts/
│   ├── bench.py               Sequential vs concurrent benchmark
│   ├── demo.py                End-to-end demo (offline, FakeVLM)
│   └── demo_ai.py             Provided AI module demo
├── data/
│   ├── samples/               Provided sample images (lost/ and found/)
│   └── images/                Runtime uploads (gitignored)
├── docs/
│   └── architecture.md        This file
├── Dockerfile                 Multi-stage build
├── docker-compose.yml         API + UI + Jaeger
├── .github/workflows/ci.yml   GitHub Actions CI
├── pyproject.toml             pytest + ruff + mypy config
├── requirements.txt           Pinned runtime + dev dependencies
└── .env.example               Environment variable template
```
