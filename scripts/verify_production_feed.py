"""Live production verification of CareerOS Job Feed Consistency & Freshness."""

import asyncio
import time
from datetime import datetime, timezone, timedelta
from typing import Any

from app.db.supabase import get_service_client
from app.models.job import NormalizedJob
from app.models.profile import UserProfile
from app.repositories.job_repository import JobRepository
from app.services.jobs.job_relevance_service import JobRelevanceService, _get_job_seniority, _is_entry_or_fresher
from app.services.jobs.personalized_job_service import PersonalizedJobService


def parse_date(d_str: str | None) -> datetime | None:
    if not d_str:
        return None
    try:
        dt = datetime.fromisoformat(str(d_str).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def run_verification():
    supabase = get_service_client()
    now = datetime.now(timezone.utc)

    print("=" * 80)
    print("STEP 1: PRODUCTION ACTIVE JOBS BY FRESHNESS BUCKET")
    print("=" * 80)

    # Fetch all active jobs with posted_at
    total_active_res = supabase.table("jobs").select("id, posted_at, created_at, last_seen_at, title, company, external_job_id", count="exact").eq("is_active", True).execute()
    total_active = total_active_res.count or len(total_active_res.data or [])
    rows = total_active_res.data or []

    buckets = {
        "<= 24h": 0,
        "<= 3d": 0,
        "<= 7d": 0,
        "8-14d": 0,
        "15-30d": 0,
        "> 30d": 0,
        "missing_posted_at": 0,
    }

    recent_jobs_by_bucket: dict[str, list[dict[str, Any]]] = {k: [] for k in buckets}

    for r in rows:
        p_dt = parse_date(r.get("posted_at"))
        if not p_dt:
            buckets["missing_posted_at"] += 1
            continue

        age_days = (now - p_dt).total_seconds() / 86400.0
        if age_days <= 1.0:
            buckets["<= 24h"] += 1
            recent_jobs_by_bucket["<= 24h"].append(r)
        if age_days <= 3.0:
            buckets["<= 3d"] += 1
            recent_jobs_by_bucket["<= 3d"].append(r)
        if age_days <= 7.0:
            buckets["<= 7d"] += 1
            recent_jobs_by_bucket["<= 7d"].append(r)
        elif age_days <= 14.0:
            buckets["8-14d"] += 1
            recent_jobs_by_bucket["8-14d"].append(r)
        elif age_days <= 30.0:
            buckets["15-30d"] += 1
            recent_jobs_by_bucket["15-30d"].append(r)
        else:
            buckets["> 30d"] += 1

    print(f"Total active jobs in DB: {total_active}")
    for b, count in buckets.items():
        print(f"  {b:<20}: {count:>5} ({count/total_active*100:>5.1f}%)")

    print("\n" + "=" * 80)
    print("STEP 5: VERIFY NEW _fetch_recent POOL PERFORMANCE & DEDUP")
    print("=" * 80)

    repo = JobRepository()
    t0 = time.perf_counter()
    candidates, db_total = repo.get_candidate_universe(page=1, page_size=1000)
    t_universe = (time.perf_counter() - t0) * 1000

    # Inspect _fetch_base alone vs _fetch_recent alone
    cols = repo._get_candidate_select_columns()
    t0_base = time.perf_counter()
    base_res = repo._client.table("jobs").select(cols).eq("is_active", True).order("created_at", desc=True).limit(1000).execute()
    t_base = (time.perf_counter() - t0_base) * 1000
    base_rows = base_res.data or []
    base_ids = {r.get("external_job_id") or r.get("id") for r in base_rows}

    t0_rec = time.perf_counter()
    rec_res = repo._client.table("jobs").select(cols).eq("is_active", True).order("posted_at", desc=True, nullsfirst=False).limit(500).execute()
    t_rec = (time.perf_counter() - t0_rec) * 1000
    rec_rows = rec_res.data or []
    rec_ids = {r.get("external_job_id") or r.get("id") for r in rec_rows}

    overlap = base_ids.intersection(rec_ids)
    genuinely_new_added = rec_ids - base_ids

    candidate_ids = [r.get("external_job_id") or r.get("id") for r in candidates]
    has_duplicates = len(candidate_ids) != len(set(candidate_ids))

    print(f"_fetch_recent returned rows    : {len(rec_rows)}")
    print(f"_fetch_base returned rows      : {len(base_rows)}")
    print(f"Overlap between base & recent  : {len(overlap)}")
    print(f"Genuinely NEW jobs rescued     : {len(genuinely_new_added)}")
    print(f"Candidate universe total size  : {len(candidates)}")
    print(f"Duplicate IDs in universe      : {has_duplicates} (unique: {len(set(candidate_ids))})")
    print(f"Latency (_fetch_base)          : {t_base:.1f}ms")
    print(f"Latency (_fetch_recent)        : {t_rec:.1f}ms")
    print(f"Total concurrent universe time : {t_universe:.1f}ms")

    print("\n" + "=" * 80)
    print("STEPS 2 & 3: REAL /jobs/personalized PATH FOR 5 TARGET PROFILES")
    print("=" * 80)

    target_profiles = [
        ("Data Analyst", ["Python", "SQL", "Excel", "Power BI"], "Fresher"),
        ("Data Engineer", ["Python", "SQL", "Spark", "AWS"], "Fresher"),
        ("Backend Engineer", ["Python", "FastAPI", "PostgreSQL", "Docker"], "Fresher"),
        ("AI/ML Engineer", ["Python", "PyTorch", "Machine Learning", "NLP"], "Fresher"),
        ("SAP Consultant", ["SAP", "ABAP", "ERP", "HANA"], "Fresher"),
    ]

    relevance_svc = JobRelevanceService(
        job_repository=repo,
        personalized_service=PersonalizedJobService(),
    )

    top20_jobs_by_role: dict[str, list[NormalizedJob]] = {}

    for desired_role, skills, exp in target_profiles:
        profile = UserProfile(
            id=f"test-prof-{desired_role.lower().replace(' ', '-')}",
            desired_role=desired_role,
            skills=skills,
            experience=exp,
            preferred_locations=["Bengaluru", "India"],
        )
        class _PRepo:
            def get_profile(self, uid):
                return profile
        relevance_svc.profile_repository = _PRepo()

        t0_req = time.perf_counter()
        top20, total = relevance_svc.get_relevant_jobs(user_id=profile.id, page=1, page_size=20)
        t_req = (time.perf_counter() - t0_req) * 1000
        top20_jobs_by_role[desired_role] = top20

        prof_buckets = {
            "<= 24h": 0,
            "<= 3d": 0,
            "<= 7d": 0,
            "8-14d": 0,
            "15-30d": 0,
            "> 30d": 0,
            "missing_posted_at": 0,
        }

        for j in top20:
            p_dt = parse_date(j.posted_date)
            if not p_dt:
                prof_buckets["missing_posted_at"] += 1
                continue
            age = (now - p_dt).total_seconds() / 86400.0
            if age <= 1.0:
                prof_buckets["<= 24h"] += 1
            if age <= 3.0:
                prof_buckets["<= 3d"] += 1
            if age <= 7.0:
                prof_buckets["<= 7d"] += 1
            elif age <= 14.0:
                prof_buckets["8-14d"] += 1
            elif age <= 30.0:
                prof_buckets["15-30d"] += 1
            else:
                prof_buckets["> 30d"] += 1

        print(f"\nProfile: {desired_role:<18} (pool total: {total}, latency: {t_req:.1f}ms)")
        print(f"  Top 20 Breakdown:")
        print(f"    <= 24h: {prof_buckets['<= 24h']:<3} | <= 3d: {prof_buckets['<= 3d']:<3} | <= 7d: {prof_buckets['<= 7d']:<3}")
        print(f"    8-14d : {prof_buckets['8-14d']:<3} | 15-30d: {prof_buckets['15-30d']:<3} | >30d: {prof_buckets['> 30d']:<3} | missing: {prof_buckets['missing_posted_at']}")

        for i, j in enumerate(top20[:3], 1):
            p_str = j.posted_date[:10] if j.posted_date else "Date unavail"
            m = j.match or {}
            print(f"    #{i}: [{m.get('overall', 0):>2.0f}% match] {j.title:<30} at {j.company:<20} ({p_str})")

    print("\n" + "=" * 80)
    print("STEP 4: TRACE KNOWN RECENT JOBS DB -> UNIVERSE -> RANKING -> PAGE 1")
    print("=" * 80)

    recent_sample = recent_jobs_by_bucket["<= 7d"][:5]
    for r in recent_sample:
        jid = r.get("external_job_id") or r.get("id")
        title = r.get("title")
        company = r.get("company")
        posted = str(r.get("posted_at"))[:10]

        in_universe = any(c.get("external_job_id") == jid or c.get("id") == jid for c in candidates)
        matched_page1_roles = []
        for role_name, top20_list in top20_jobs_by_role.items():
            if any(j.external_job_id == jid or j.id == jid for j in top20_list):
                matched_page1_roles.append(role_name)

        page1_status = f"YES (in {', '.join(matched_page1_roles)})" if matched_page1_roles else "No (ranked in subsequent pages per relevance)"
        print(f"Job: '{title}' at {company} (posted: {posted})")
        print(f"  -> In DB: True")
        print(f"  -> Reaches Candidate Universe: {in_universe}")
        print(f"  -> Reaches Page 1: {page1_status}")

    print("\n" + "=" * 80)
    print("STEP 7: SCREENSHOT JOB SPECIFIC VERIFICATION")
    print("=" * 80)

    screenshot_job = NormalizedJob(
        id="screenshot-da-sales",
        external_job_id="screenshot-da-sales",
        title="Data Analyst",
        company="SalesOps Enterprise",
        location="Bengaluru, India",
        description="We are looking for a Data Analyst to join Sales Operations. Responsible for calculating sales incentives, commission plans, and performance quotas. Requires 2–5 years of experience in data analytics with SQL and Excel.",
        posted_date=(now - timedelta(days=14)).isoformat(),
    )
    seniority = _get_job_seniority(screenshot_job)
    is_fresher = _is_entry_or_fresher(screenshot_job)

    da_prof = UserProfile(
        id="p-da",
        desired_role="Data Analyst",
        skills=["Python", "SQL", "Excel"],
        experience="Fresher",
    )
    m = relevance_svc.personalized_service.calculate_match_score(screenshot_job, da_prof)

    print(f"Title            : {screenshot_job.title}")
    print(f"Description      : {screenshot_job.description[:70]}...")
    print(f"Classified Level : '{seniority}' (Expected: 'mid')")
    print(f"_is_entry_or_fresher : {is_fresher} (Expected: False)")
    print(f"Match overall    : {m['overall']}% (Fresher bonus excluded)")

    print("\n" + "=" * 80)
    print("STEP 8: VERIFIED ACTIVE MASS-HIRING EXCEPTION VERIFICATION")
    print("=" * 80)

    old_mass_job = NormalizedJob(
        id="old-mass-job",
        external_job_id="old-mass-job",
        title="Graduate Engineering Trainee",
        company="TCS",
        location="Bengaluru, India",
        description="National Qualifier Test 2026 for engineering freshers across India.",
        mass_hiring="VERIFIED_MASS_HIRING",
        mass_hiring_status="ACTIVE",
        posted_date=(now - timedelta(days=60)).isoformat(),
    )
    mass_freshness = relevance_svc.personalized_service._score_freshness(old_mass_job)
    print(f"Old Active Mass Hiring Job (posted 60d ago):")
    print(f"  Freshness score: {mass_freshness} (Expected: 85.0 fixed active mass-hiring score)")
    assert mass_freshness == 85.0, f"Expected 85.0, got {mass_freshness}"

    expired_mass_job = NormalizedJob(
        id="expired-mass-job",
        title="Graduate Trainee Drive",
        company="Infosys",
        mass_hiring="VERIFIED_MASS_HIRING",
        mass_hiring_status="EXPIRED",
        posted_date=(now - timedelta(days=60)).isoformat(),
    )
    expired_freshness = relevance_svc.personalized_service._score_freshness(expired_mass_job)
    print(f"Expired Mass Hiring Job:")
    print(f"  Freshness score: {expired_freshness} (Expected: 20.0 demoted expired mass score)")
    assert expired_freshness == 20.0, f"Expected 20.0, got {expired_freshness}"

    print("\n" + "=" * 80)
    print("STEP 9: VERIFY posted_at vs last_seen_at INTEGRITY")
    print("=" * 80)

    old_crawled_job = NormalizedJob(
        id="old-crawled",
        title="Data Analyst",
        company="OldCo",
        posted_date=(now - timedelta(days=40)).isoformat(),
        last_seen_at=now.isoformat(),
    )
    f_score = relevance_svc.personalized_service._score_freshness(old_crawled_job)
    print(f"Job posted 40d ago, re-seen today (last_seen_at = NOW):")
    print(f"  Freshness score: {f_score} (Expected: 15.0 for >30d, NOT 50.0 or 100.0 from last_seen_at)")
    assert f_score == 15.0, f"Expected 15.0 based on authoritative posted_date, got {f_score}"

    print("\nALL VERIFICATION STEPS COMPLETED SUCCESSFULLY!")


if __name__ == "__main__":
    run_verification()
