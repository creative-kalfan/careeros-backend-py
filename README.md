# CareerOS Backend (Python / FastAPI)

Feature-by-feature reimplementation of the TypeScript `careeros-backend`, built
with **FastAPI**. The existing TypeScript backend is left untouched as reference
until each feature is confirmed working in Python.

## Current status

| Feature | Status |
|---|---|
| Project scaffold | ✅ Done |
| Authentication & session handling | ✅ Done (this feature) |
| ATS discovery / adapters / aggregators | ⏳ Not started |
| RoleClassifier / DeadlineExtractor | ⏳ Not started |
| Crawl runner / job search / recommendations | ⏳ Not started |
| Notifications / event bus / ATS scoring | ⏳ Not started |
| Resume parsing / optimizer | ⏳ Not started |

## Why `requirements.txt` (not `pyproject.toml`)

This is a plain FastAPI service with no packaging or distribution requirement —
there's no console script, no wheel, no `pip install .` need. A simple pinned
`requirements.txt` is the lowest-friction option: `pip install -r requirements.txt`
just works, and the pins make the environment reproducible. If we later need to
publish the service as a package or add build tooling, we can migrate to
`pyproject.toml` then.

## Project layout

```
careeros-backend-py/
  app/
    main.py              # FastAPI app instance, router registration, exception handlers
    config.py            # pydantic-settings env loading
    dependencies.py      # get_current_user / get_current_admin FastAPI dependencies
    auth/
      service.py         # JWT verification, profile lookup/auto-create, RLS-fixed client
      router.py          # /auth/me, /auth/me/admin
  tests/
    test_auth.py         # live-Supabase tests (incl. RLS regression)
  requirements.txt
  .env.example
  README.md
```

## Setup

```bash
cd careeros-backend-py
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env   # then fill in real values
```

## Run the server

```bash
uvicorn app.main:app --reload
```

- `GET /health` — liveness probe
- `GET /auth/me` — requires `Authorization: Bearer <JWT>`; returns `{id, email, role}`
- `GET /auth/me/admin` — same, but 403 unless `role == "admin"`
- Interactive docs at `http://localhost:8000/docs`

## The RLS fix (why auth is done this way)

The original TypeScript `lib/auth.ts` had a real bug: it created a Supabase
client **without** attaching the caller's JWT, so any query against an
RLS-protected table (e.g. `profiles`) silently returned empty/null results.

In this Python implementation, `app/auth/service.py::_create_authenticated_client`
creates the Supabase client **with the JWT attached** via
`options={"auth": {"access_token": jwt, ...}}`. Every subsequent query — profile
lookup, auto-create, re-read — runs under the caller's RLS context. The
`test_rls_authenticated_client_returns_own_row` test is the explicit regression
guard for this.

## Running the tests

The tests hit a **live Supabase project** (no mocks) because the whole point is
to verify RLS actually works with the token attached. Set these in `.env`:

```
NEXT_PUBLIC_SUPABASE_URL=...
NEXT_PUBLIC_SUPABASE_ANON_KEY=...
TEST_USER_EMAIL=...        # a regular (non-admin) user
TEST_USER_PASSWORD=...
TEST_ADMIN_EMAIL=...       # a user whose profiles.role == 'admin'
TEST_ADMIN_PASSWORD=...
```

Then:

```bash
pytest -v
```

The critical test is `test_rls_authenticated_client_returns_own_row` — it must
pass (return the user's own profile row, non-null) for this feature to be
considered done.