"""Verify India-first Adzuna sourcing and ranking logic."""
import asyncio
import os


def _load_env() -> None:
    """Load .env into os.environ so Adzuna credentials are available."""
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())


_load_env()

from app.crawlers.aggregators.adzuna import AdzunaAdapter
from app.models.job import NormalizedJob
from app.services.jobs.job_relevance_service import _india_first_score


async def main() -> None:
    adapter = AdzunaAdapter()

    print("=== 1. Adzuna India search (country='in') ===")
    india_jobs = await adapter.search_by_query("software engineer", country="in", results_per_page=10)
    print(f"India search returned {len(india_jobs)} jobs")
    for j in india_jobs[:5]:
        print(f"  - {j.title} | {j.company} | {j.location}")

    print()
    print("=== 2. Adzuna remote/global search (country='gb', query='remote') ===")
    remote_jobs = await adapter.search_by_query("remote", country="gb", results_per_page=10)
    print(f"Remote search returned {len(remote_jobs)} jobs")
    for j in remote_jobs[:5]:
        print(f"  - {j.title} | {j.company} | {j.location}")

    print()
    print("=== 3. India-first ranking score on real locations ===")
    samples = [
        NormalizedJob(title="t", company="c", location="Bengaluru, Karnataka, India"),
        NormalizedJob(title="t", company="c", location="Hyderabad, Telangana, India"),
        NormalizedJob(title="t", company="c", location="Remote - India"),
        NormalizedJob(title="t", company="c", location="Remote", remote=True),
        NormalizedJob(title="t", company="c", location="San Francisco, CA"),
        NormalizedJob(title="t", company="c", location="London, UK"),
    ]
    for s in samples:
        print(f"  score={_india_first_score(s)}  location={s.location!r} remote={s.remote}")


if __name__ == "__main__":
    asyncio.run(main())