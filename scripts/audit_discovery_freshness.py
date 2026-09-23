"""Production audit: discovery freshness, provider crawl state, latency profile."""

from __future__ import annotations

import asyncio
import json
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone

try:
    from dotenv import load_dotenv
    load_dotenv(".env")
except Exception:
    pass

from app.db.supabase import get_service_client
from app.repositories.job_repository import JobRepository


def parse_dt(s):
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def age_days(dt, now):
    return (now - dt).total_seconds() / 86400.0


def audit_db():
    supabase = get_service_client()
    now = datetime.now(timezone.utc)
    print("=" * 90)
    print("SECTION 1: DB FRESHNESS + PER-SOURCE BREAKDOWN")
    print("=" * 90)

    # Fetch all jobs (active + inactive) with key fields
    res = supabase.table("jobs").select(
        "id, title, company, location, posted_at, created_at, last_seen_at, "
        "first_seen_at, last_crawled_at, source_platform, external_job_id, "
        "is_active, experience_level, role_category, mass_hiring, mass_hiring_status"
    ).limit(10000).execute()
    rows = res.data or []
    print(f"Total jobs fetched: {len(rows)}")

    active = [r for r in rows if r.get("is_active")]
    print(f"Active: {len(active)}, Inactive: {len(rows) - len(active)}")

    # Freshness buckets on active jobs by posted_at
    buckets = Counter()
    for r in active:
        p = parse_dt(r.get("posted_at"))
        if not p:
            buckets["missing_posted_at"] += 1
            continue
        d = age_days(p, now)
        if d <= 1:
            buckets["<=24h"] += 1
        elif d <= 3:
            buckets["<=3d"] += 1
        elif d <= 7:
            buckets["<=7d"] += 1
        elif d <= 14:
            buckets["8-14d"] += 1
        elif d <= 30:
            buckets["15-30d"] += 1
        else:
            buckets[">30d"] += 1
    print("\nActive jobs by posted_at age:")
    for k in ["<=24h", "<=3d", "<=7d", "8-14d", "15-30d", ">30d", "missing_posted_at"]:
        print(f"  {k:20s}: {buckets[k]}")

    # created_at freshness (when job row was inserted)
    created_buckets = Counter()
    for r in active:
        c = parse_dt(r.get("created_at"))
        if not c:
            created_buckets["missing"] += 1
            continue
        d = age_days(c, now)
        if d <= 1:
            created_buckets["<=24h"] += 1
        elif d <= 3:
            created_buckets["<=3d"] += 1
        elif d <= 7:
            created_buckets["<=7d"] += 1
        elif d <= 14:
            created_buckets["8-14d"] += 1
        elif d <= 30:
            created_buckets["15-30d"] += 1
        else:
            created_buckets[">30d"] += 1
    print("\nActive jobs by created_at age (insertion time):")
    for k in ["<=24h", "<=3d", "<=7d", "8-14d", "15-30d", ">30d", "missing"]:
        print(f"  {k:20s}: {created_buckets[k]}")

    # last_seen_at freshness (when last observed by any crawl)
    seen_buckets = Counter()
    for r in active:
        c = parse_dt(r.get("last_seen_at"))
        if not c:
            seen_buckets["missing"] += 1
            continue
        d = age_days(c, now)
        if d <= 1:
            seen_buckets["<=24h"] += 1
        elif d <= 3:
            seen_buckets["<=3d"] += 1
        elif d <= 7:
            seen_buckets["<=7d"] += 1
        elif d <= 14:
            seen_buckets["8-14d"] += 1
        elif d <= 30:
            seen_buckets["15-30d"] += 1
        else:
            seen_buckets[">30d"] += 1
    print("\nActive jobs by last_seen_at age (last crawl observation):")
    for k in ["<=24h", "<=3d", "<=7d", "8-14d", "15-30d", ">30d", "missing"]:
        print(f"  {k:20s}: {seen_buckets[k]}")

    # Per-source breakdown
    print("\nPer-source breakdown (active jobs):")
    print(f"  {'source':20s} {'active':>7} {'<=24h_p':>8} {'<=3d_p':>7} {'<=7d_p':>7} "
          f"{'<=24h_c':>8} {'<=3d_c':>7} {'<=24h_s':>8} {'<=3d_s':>7} {'no_post':>8} {'last_seen_max':>22}")
    by_src = defaultdict(list)
    for r in active:
        by_src[r.get("source_platform") or "unknown"].append(r)
    for src in sorted(by_src.keys()):
        rs = by_src[src]
        p24 = p3 = p7 = 0
        c24 = c3 = 0
        s24 = s3 = 0
        no_p = 0
        max_seen = None
        for r in rs:
            p = parse_dt(r.get("posted_at"))
            if p:
                d = age_days(p, now)
                if d <= 1: p24 += 1
                if d <= 3: p3 += 1
                if d <= 7: p7 += 1
            else:
                no_p += 1
            c = parse_dt(r.get("created_at"))
            if c:
                d = age_days(c, now)
                if d <= 1: c24 += 1
                if d <= 3: c3 += 1
            s = parse_dt(r.get("last_seen_at"))
            if s:
                d = age_days(s, now)
                if d <= 1: s24 += 1
                if d <= 3: s3 += 1
                if max_seen is None or s > max_seen:
                    max_seen = s
        print(f"  {src:20s} {len(rs):>7} {p24:>8} {p3:>7} {p7:>7} "
              f"{c24:>8} {c3:>7} {s24:>8} {s3:>7} {no_p:>8} "
              f"{max_seen.isoformat() if max_seen else 'never':>22}")

    # Jobs created in last 24h / 3d (insertion, any source)
    print("\nJobs INSERTED (created_at) in last windows:")
    for window, hrs in [("24h", 24), ("3d", 72), ("7d", 168)]:
        cutoff = now.timestamp() - hrs * 3600
        n = sum(1 for r in rows
                if (c := parse_dt(r.get("created_at"))) and c.timestamp() >= cutoff)
        n_active = sum(1 for r in active
                       if (c := parse_dt(r.get("created_at"))) and c.timestamp() >= cutoff)
        print(f"  {window}: {n} inserted ({n_active} still active)")

    # India + target-role + fresher among recent
    print("\nRecent (created <=7d) active jobs: India / target-role / fresher split")
    target_kw = ["data analyst", "data engineer", "backend", "software engineer",
                 "machine learning", "ai ", "ml ", "sap", "python", "java",
                 "full stack", "devops", "analytics"]
    fresher_kw = ["fresher", "junior", "entry", "trainee", "intern", "graduate",
                  "associate", "new grad", "early career"]
    india_tok = ["india", "bengaluru", "bangalore", "hyderabad", "pune", "mumbai",
                 "chennai", "delhi", "noida", "gurgaon", "gurugram", "remote"]
    cutoff7 = now.timestamp() - 7 * 86400
    recent = [r for r in active
              if (c := parse_dt(r.get("created_at"))) and c.timestamp() >= cutoff7]
    india_n = sum(1 for r in recent
                  if any(t in (r.get("location") or "").lower() for t in india_tok))
    target_n = sum(1 for r in recent
                   if any(t in (r.get("title") or "").lower() for t in target_kw))
    fresher_n = sum(1 for r in recent
                    if any(t in (r.get("title") or "").lower() for t in fresher_kw)
                    or (r.get("experience_level") or "").lower() in ("entry", "fresher", "intern"))
    unique_companies = len({(r.get("company") or "").lower() for r in recent if r.get("company")})
    print(f"  inserted<=7d active: {len(recent)}")
    print(f"  india-located: {india_n}, target-role title: {target_n}, fresher: {fresher_n}, unique companies: {unique_companies}")

    # Same for posted_at <=7d
    cutoff7p = now.timestamp() - 7 * 86400
    recent_p = [r for r in active
                if (p := parse_dt(r.get("posted_at"))) and p.timestamp() >= cutoff7p]
    india_np = sum(1 for r in recent_p
                   if any(t in (r.get("location") or "").lower() for t in india_tok))
    target_np = sum(1 for r in recent_p
                    if any(t in (r.get("title") or "").lower() for t in target_kw))
    fresher_np = sum(1 for r in recent_p
                     if any(t in (r.get("title") or "").lower() for t in fresher_kw)
                     or (r.get("experience_level") or "").lower() in ("entry", "fresher", "intern"))
    print(f"\n  posted_at<=7d active: {len(recent_p)}")
    print(f"  india: {india_np}, target-role: {target_np}, fresher: {fresher_np}")


async def audit_redis_crawl_status():
    print("\n" + "=" * 90)
    print("SECTION 2: REDIS CRAWL STATUS (last crawl per target)")
    print("=" * 90)
    from app.crawlers.crawl_registry import all_targets
    from app.workers.settings import get_redis_pool

    redis = await get_redis_pool()
    now = datetime.now(timezone.utc)
    by_source = defaultdict(lambda: {
        "targets": 0, "success": 0, "failed": 0, "unknown": 0,
        "last_success": None, "last_any": None,
        "last_inserted": 0, "last_discovered": 0, "last_error": None,
        "statuses": [],
    })
    try:
        for target in all_targets():
            st = by_source[target.source]
            st["targets"] += 1
            try:
                raw = await redis.get(f"crawl_status:{target.source}:{target.slug}")
            except Exception:
                raw = None
            if not raw:
                st["unknown"] += 1
                st["statuses"].append((target.slug, "unknown", None, 0, 0))
                continue
            data = json.loads(raw)
            status = data.get("status", "?")
            completed = data.get("completed_at")
            inserted = data.get("inserted", 0)
            discovered = data.get("discovered", 0)
            st["statuses"].append((target.slug, status, completed, inserted, discovered))
            if status == "success":
                st["success"] += 1
                if completed and (not st["last_success"] or completed > st["last_success"]):
                    st["last_success"] = completed
                    st["last_inserted"] = inserted
                    st["last_discovered"] = discovered
            elif status == "failed":
                st["failed"] += 1
                st["last_error"] = data.get("error", "")
            if completed and (not st["last_any"] or completed > st["last_any"]):
                st["last_any"] = completed

        print(f"\n{'source':20s} {'tgts':>4} {'ok':>3} {'fail':>4} {'unk':>4} "
              f"{'last_success':>26} {'ins':>4} {'disc':>5} {'age_h':>7}")
        for src in sorted(by_source.keys()):
            st = by_source[src]
            ls = st["last_success"]
            age = ""
            if ls:
                dt = parse_dt(ls)
                if dt:
                    age = f"{age_days(dt, now):.1f}"
            print(f"{src:20s} {st['targets']:>4} {st['success']:>3} {st['failed']:>4} "
                  f"{st['unknown']:>4} {str(ls or 'NEVER'):>26} "
                  f"{st['last_inserted']:>4} {st['last_discovered']:>5} {age:>7}")

        # Detail for adzuna + sample of others
        print("\nAdzuna target detail:")
        for slug, status, completed, inserted, discovered in by_source["adzuna"]["statuses"]:
            print(f"  slug={slug!r} status={status} completed={completed} "
                  f"inserted={inserted} discovered={discovered}")
        print("\nFailed targets (all sources):")
        any_fail = False
        for src, st in by_source.items():
            for slug, status, completed, inserted, discovered in st["statuses"]:
                if status == "failed":
                    any_fail = True
                    print(f"  {src}:{slug} completed={completed}")
        if not any_fail:
            print("  (none recorded in Redis — note 7-day TTL)")

        print("\nTargets with NO status (never crawled or TTL expired):")
        for src, st in by_source.items():
            for slug, status, completed, inserted, discovered in st["statuses"]:
                if status == "unknown":
                    print(f"  {src}:{slug}")
    finally:
        await redis.aclose()


def audit_latency():
    print("\n" + "=" * 90)
    print("SECTION 3: PERSONALIZED FEED LATENCY PROFILE")
    print("=" * 90)
    from app.models.profile import UserProfile
    from app.services.jobs.job_relevance_service import JobRelevanceService
    from app.services.jobs.personalized_job_service import PersonalizedJobService

    repo = JobRepository()

    # Warm-up (column probes)
    t0 = time.perf_counter()
    _ = repo._get_candidate_select_columns()
    print(f"Column probe (warm): {(time.perf_counter()-t0)*1000:.1f}ms")

    # Stage: candidate universe (5 concurrent queries)
    times = {}
    for i in range(3):
        t0 = time.perf_counter()
        rows, total = repo.get_candidate_universe(page=1, page_size=1000)
        times[f"universe_run{i}"] = (time.perf_counter() - t0) * 1000
    print(f"Candidate universe (3 runs): {[f'{v:.0f}ms' for v in times.values()]} rows={len(rows)} total={total}")

    # Isolate individual pool queries
    cols = repo._get_candidate_select_columns()
    for name, fn in [
        ("_fetch_base", lambda: repo._client.table("jobs").select(cols, count="exact").eq("is_active", True).order("created_at", desc=True).range(0, 999).execute()),
        ("_fetch_recent", lambda: repo._client.table("jobs").select(cols).eq("is_active", True).order("posted_at", desc=True, nullsfirst=False).limit(500).execute()),
        ("_fetch_mass", lambda: repo._client.table("jobs").select(cols).eq("is_active", True).eq("mass_hiring", "VERIFIED_MASS_HIRING").eq("mass_hiring_status", "ACTIVE").execute()),
        ("_fetch_freshers", lambda: repo._client.table("jobs").select(cols).eq("is_active", True).or_(
            "title.ilike.%intern%,title.ilike.%fresher%,title.ilike.%junior%,title.ilike.%trainee%,title.ilike.%entry%,title.ilike.%associate%,experience_level.ilike.%entry%,experience_level.ilike.%fresher%,experience_level.ilike.%intern%"
        ).execute()),
    ]:
        t0 = time.perf_counter()
        try:
            fn()
            print(f"  {name:20s}: {(time.perf_counter()-t0)*1000:.1f}ms")
        except Exception as e:
            print(f"  {name:20s}: FAILED {e}")

    # Full get_relevant_jobs with profile
    svc = JobRelevanceService(job_repository=repo, personalized_service=PersonalizedJobService())
    profiles = [
        ("Data Analyst", ["Python", "SQL", "Excel", "Power BI"], "Fresher"),
        ("Data Engineer", ["Python", "SQL", "Spark", "AWS"], "Fresher"),
        ("Backend Engineer", ["Python", "FastAPI", "PostgreSQL", "Docker"], "Fresher"),
        ("AI/ML Engineer", ["Python", "PyTorch", "Machine Learning", "NLP"], "Fresher"),
        ("SAP Consultant", ["SAP", "ABAP", "ERP", "HANA"], "Fresher"),
    ]
    for desired_role, skills, exp in profiles:
        profile = UserProfile(
            id=f"lat-{desired_role.lower().replace(' ', '-')}",
            desired_role=desired_role, skills=skills, experience=exp,
            preferred_locations=["Bengaluru", "India"],
        )
        class _PRepo:
            def get_profile(self, uid):
                return profile
        svc.profile_repository = _PRepo()

        # Stage breakdown
        t0 = time.perf_counter()
        _ = svc.profile_repository.get_profile("x")
        t_profile = (time.perf_counter() - t0) * 1000

        t0 = time.perf_counter()
        cand_rows, cand_total = repo.get_candidate_universe(page=1, page_size=1000)
        t_cand = (time.perf_counter() - t0) * 1000

        t0 = time.perf_counter()
        from app.models.job import NormalizedJob
        jobs = [NormalizedJob.model_validate(row) for row in cand_rows]
        t_validate = (time.perf_counter() - t0) * 1000

        t0 = time.perf_counter()
        filtered = svc.personalized_service.filter_jobs(jobs, profile, strict=False)
        t_filter = (time.perf_counter() - t0) * 1000

        t0 = time.perf_counter()
        for job in filtered:
            job.match = svc.personalized_service.calculate_match_score(job, profile)
        t_score = (time.perf_counter() - t0) * 1000

        # Full end-to-end
        t0 = time.perf_counter()
        top20, total = svc.get_relevant_jobs(user_id=profile.id, page=1, page_size=20)
        t_full = (time.perf_counter() - t0) * 1000

        print(f"\n{desired_role}:")
        print(f"  profile={t_profile:.1f}ms cand={t_cand:.1f}ms validate={t_validate:.1f}ms "
              f"filter={t_filter:.1f}ms score({len(filtered)} jobs)={t_score:.1f}ms")
        print(f"  FULL get_relevant_jobs: {t_full:.1f}ms (pool={total})")


async def main():
    audit_db()
    await audit_redis_crawl_status()
    audit_latency()


if __name__ == "__main__":
    asyncio.run(main())
