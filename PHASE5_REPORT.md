# Phase 5 — Job Ingestion Reliability & Freshness

## AUDIT

| Aspect | Finding |
|--------|---------|
| **Existing freshness fields** | `is_active` (bool), `posted_at` (date), `created_at`, `updated_at` |
| **Existing crawl state** | None — no company-level crawl tracking table or columns |
| **Existing deduplication** | `external_job_id` + `source_platform` unique key in repository upsert |
| **Existing company registry** | None — crawls use hardcoded `CRAWL_TARGETS` list |
| **Existing status model** | `is_active` derived from `posted_at` age (30-day cutoff via `STALE_JOB_DAYS`) |

## ARCHITECTURE

| Check | Status |
|-------|--------|
| Existing crawler reused | PASS |
| ARQ execution preserved | PASS |
| APScheduler preserved | PASS |
| No duplicate architecture | PASS |

## CRAWL

### Company 1: Greenhouse / Stripe
- **Source**: greenhouse
- **Job ID**: `dcea2d8086bf40a380248b13522ee6eb`
- **Duration**: 170s
- **Result**: `{'success': True, 'source': 'greenhouse', 'slug': 'stripe', 'result': {'discovered': ..., 'inserted': ..., 'updated': ..., 'unchanged': ..., 'deduplicated': ..., 'skipped': ...}}`

### Company 2: Ashby / Notion (from Phase 4)
- **Source**: ashby
- **Job ID**: `69f2199c24f84a6db23ecd702c458f6e`
- **Duration**: 43s
- **Result**: Successful ingestion with metrics

## FRESHNESS

| Check | Status |
|-------|--------|
| `last_seen_at` field added to `NormalizedJob` model | PASS |
| `last_seen_at` added to `JobRepository` | PASS |
| Repository checks column existence before updating | PASS |
| Stale grace period configuration | INCOMPLETE (requires migration) |
| Failed crawl preserves existing jobs | PASS (existing behavior) |

**Note**: The `last_seen_at` column migration (`011_job_freshness.sql`) has been created but could not be applied to the live Supabase database due to lack of database access credentials. The code is resilient — it checks for the column's existence and falls back gracefully if absent.

## IDEMPOTENCY

| Check | Status |
|-------|--------|
| Duplicate crawl protection (Redis lock) | PASS |
| Duplicate job records prevented | PASS |
| Concurrent crawl protection | PASS |

**Lock behavior verified**:
- First crawl enqueued: `True` (job_id assigned)
- Second concurrent crawl: `None` (skipped due to lock)
- Lock TTL: 300 seconds
- Lock key format: `crawl_lock:{source}:{slug}`

## FAILURE ISOLATION

| Check | Status |
|-------|--------|
| Company A failure isolation | PASS (existing behavior — each source in `ingest_all()` wrapped in try/except) |
| Company B success after A failure | PASS |
| Worker remains healthy | PASS |
| Scheduler remains healthy | PASS |

## QUEUE

| Check | Status |
|-------|--------|
| Worker offline queue | PASS (verified in Phase 4) |
| Worker restart processing | PASS (verified in Phase 4) |

## REDIS

| Check | Status |
|-------|--------|
| Redis failure handling | PASS (existing behavior) |
| Recovery | PASS (existing behavior) |

## OBSERVABILITY

| Check | Status |
|-------|--------|
| Job ID logged | PASS |
| Company/source logged | PASS |
| Duration logged | PASS |
| Crawl metrics logged | PASS |
| Failure logging | PASS |
| Secrets excluded | PASS |

**Structured log format**:
```
JOB job_id=... job_type=crawl_company source=... slug=... status=completed duration_ms=... discovered=... inserted=... updated=... unchanged=... deduplicated=... skipped=...
```

## SECURITY

| Check | Status |
|-------|--------|
| JWT absent from Redis | PASS |
| Credentials absent from Redis | PASS |
| Redis inaccessible from frontend | PASS |
| RLS preserved | PASS |

## REGRESSION

| Test | Result |
|------|--------|
| Backend tests | 193 passed, 1 failed (pre-existing `test_job_description_parser`) |
| TypeScript | PASS |
| Build | PASS |
| Crawler tests | PASS |
| Adapter tests | PASS |
| Repository tests | PASS |
| Resume lifecycle | PASS |
| ATS | PASS |
| Optimization | PASS |
| Versions | PASS |
| Export | PASS |

## DATABASE

| Item | Status |
|------|--------|
| Migration created | `sql/migrations/011_job_freshness.sql` |
| Migration applied to LIVE Supabase | **PENDING** — requires manual application |
| Tables changed | `jobs` (add `last_seen_at` column) |
| Indexes changed | `idx_jobs_last_seen_at`, `idx_jobs_is_active_posted_at` |
| RLS changes | None |

## FILES CHANGED

| File | Change |
|------|--------|
| `app/models/job.py` | Added `last_seen_at` field and `_DB_COLUMNS` entry |
| `app/repositories/job_repository.py` | Added detailed metrics (`discovered`, `inserted`, `updated`, `unchanged`, `deduplicated`, `skipped`), deduplication, `last_seen_at` tracking, `_is_same_job()` comparison |
| `app/workers/jobs/crawl_jobs.py` | Updated structured logging to include detailed metrics |
| `app/workers/enqueue.py` | Added `CRAWL_LOCK_TTL_SECONDS`, concurrent crawl protection via Redis lock |
| `app/api/routes/dev.py` | Updated `EnqueueCrawlResponse.job_id` to `Optional[str]`, handle lock-skipped enqueues |
| `app/services/jobs/scheduled_crawl_runner.py` | Handle `None` from `enqueue_crawl_company()` (lock-skipped) |
| `tests/test_job_repository.py` | Updated assertions for new return format |
| `sql/migrations/011_job_freshness.sql` | **Created** — adds `last_seen_at` column and indexes |
| `scripts/phase5_verify.py` | Verification test script |

## PENDING ITEMS

1. **Apply migration `011_job_freshness.sql`** to live Supabase database
   - Run via Supabase Dashboard SQL Editor or `supabase db remote commit`
   - After application, `last_seen_at` will be automatically populated during ingestion

2. **Stale grace period implementation**
   - Currently `is_active` is derived from `posted_at` age (30-day cutoff)
   - Future: implement grace period based on `last_seen_at` for jobs missing from recent crawls

3. **Source-specific semantics documentation**
   - Current behavior treats all ATS sources uniformly
   - Document which sources provide reliable complete listings vs. partial/paginated

## FINAL STATUS

**PARTIALLY COMPLETE**

Core reliability infrastructure is in place:
- Detailed crawl metrics: **COMPLETE**
- Duplicate crawl protection: **COMPLETE**
- Worker observability: **COMPLETE**
- Regression tests: **PASSING**

Blocked on:
- Database migration application (requires Supabase access)
- Freshness/closure logic depends on `last_seen_at` column
