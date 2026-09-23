"""Adzuna freshness probe: prove external fresh India/target-role inventory exists.

Queries the required matrix (fresher DE, junior DE, entry DE, graduate DE,
trainee DE, fresher SAP, junior SAP, entry SAP, SAP trainee) plus existing
Data Analyst / Backend / AI-ML queries. Reports raw/valid/India/role/fresher
counts and posted_at age distribution. No DB writes.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

try:
    from dotenv import load_dotenv
    load_dotenv(".env")
except Exception:
    pass

from app.crawlers.aggregators.adzuna import AdzunaAdapter
from app.services.jobs.india_geography import classify_india_relevance
from app.services.jobs.ingestion_validation import TARGET_ROLE_KEYWORDS
from app.services.jobs.job_service import JobService, validate_job

QUERIES = [
    "fresher data engineer India",
    "junior data engineer India",
    "entry level data engineer India",
    "graduate data engineer India",
    "trainee data engineer India",
    "SAP fresher India",
    "junior SAP India",
    "entry level SAP India",
    "SAP trainee India",
    "data analyst India",
    "backend engineer India",
    "machine learning India",
]


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


def role_bucket(title: str):
    lowered = (title or "").lower()
    for bucket, kws in TARGET_ROLE_KEYWORDS.items():
        if any(k in lowered for k in kws):
            return bucket
    return None


async def main():
    service = JobService()
    now = datetime.now(timezone.utc)
    async with AdzunaAdapter() as adapter:
        print(f"{'query':36s} {'raw':>4} {'valid':>5} {'india':>5} {'role':>4} "
              f"{'fresher':>7} {'<=3d':>4} {'<=7d':>4} {'<=30d':>5} {'no_date':>7}")
        totals = dict(raw=0, valid=0, india=0, role=0, fresher=0, d3=0, d7=0, d30=0, nod=0)
        for q in QUERIES:
            try:
                crawled = await adapter.search_by_query(q, country="in", results_per_page=50)
            except Exception as e:
                print(f"{q:36s} ERROR {e}")
                continue
            raw = len(crawled)
            valid = india = role = fresher = d3 = d7 = d30 = nod = 0
            for cj in crawled:
                job = service.normalize_and_classify(cj)
                status, _ = validate_job(job)
                if status == "INVALID":
                    continue
                valid += 1
                if classify_india_relevance(job.location, job.remote) == "INDIA":
                    india += 1
                if role_bucket(job.title):
                    role += 1
                tl = (job.title or "").lower()
                if any(k in tl for k in ("fresher", "junior", "entry", "trainee",
                                          "graduate", "intern", "associate")):
                    fresher += 1
                p = parse_dt(job.posted_date)
                if not p:
                    nod += 1
                else:
                    age = (now - p).total_seconds() / 86400
                    if age <= 30:
                        d30 += 1
                    if age <= 7:
                        d7 += 1
                    if age <= 3:
                        d3 += 1
            print(f"{q:36s} {raw:>4} {valid:>5} {india:>5} {role:>4} "
                  f"{fresher:>7} {d3:>4} {d7:>4} {d30:>5} {nod:>7}")
            for k, v in dict(raw=raw, valid=valid, india=india, role=role,
                             fresher=fresher, d3=d3, d7=d7, d30=d30, nod=nod).items():
                totals[k] += v
        print(f"{'TOTAL':36s} {totals['raw']:>4} {totals['valid']:>5} {totals['india']:>5} "
              f"{totals['role']:>4} {totals['fresher']:>7} {totals['d3']:>4} "
              f"{totals['d7']:>4} {totals['d30']:>5} {totals['nod']:>7}")


if __name__ == "__main__":
    asyncio.run(main())
