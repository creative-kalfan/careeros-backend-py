# CareerOS Backend (Python / FastAPI)

The canonical backend service for CareerOS, built with **FastAPI**, **Supabase** (PostgreSQL RLS), **ARQ + Redis**, and **APScheduler**.

Authoritative documentation: See [COMPLETE_SYSTEM.md](COMPLETE_SYSTEM.md) and [AGENTS.md](AGENTS.md).

## Architecture

- **Runtime:** Python 3.11+ / FastAPI / Uvicorn
- **Database:** Supabase PostgreSQL with Row Level Security (RLS)
- **Background Tasks:** ARQ + Redis (scheduled crawls, job processing)
- **Scheduler:** APScheduler (recurring crawl orchestration)
- **LLM Gateway:** Controlled multi-provider suggestions engine (Groq, Gemini, Mistral, OpenRouter)
- **Testing:** Pytest with hermetic test execution (live network tests isolated behind `-m live`)

## Repository Layout

```
careeros-backend-py/
├── app/
│   ├── api/routes/          # FastAPI route handlers (thin)
│   ├── auth/                # JWT verification & RLS-aware client
│   ├── crawlers/            # ATS adapters & aggregators (Ashby, Greenhouse, Lever, etc.)
│   ├── db/                  # Supabase database clients & RPC wrappers
│   ├── events/              # In-process typed EventBus & subscribers
│   ├── llm/                 # Multi-provider LLM gateway
│   ├── models/              # Domain & Pydantic models
│   ├── parsing/             # Resume parsing (PyMuPDF, docx)
│   ├── repositories/        # Database access layer
│   ├── schemas/             # Request & response schemas
│   ├── services/            # Core business & domain logic
│   └── workers/             # ARQ worker functions & scheduler
├── sql/migrations/          # Idempotent numbered SQL migrations
├── tests/                   # Hermetic automated test suite
├── docs/                    # Architectural docs & historical archives
│   └── archive/             # Archived reference documents
└── scripts/                 # Operations and diagnostic scripts
    ├── ops/                 # Operational maintenance scripts
    └── manual/              # Manual diagnostic & verification scripts
```

## Running Tests

```bash
# Run hermetic test suite (default, excludes live external network calls)
python -m pytest

# Run with visual tests enabled (requires pinned Docker environment with exact fonts)
RUN_VISUAL_TESTS=1 python -m pytest tests/test_resume_studio_regression.py

# Run live network / live Supabase integration tests
python -m pytest -m live
```