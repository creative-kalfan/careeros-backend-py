"""Print 2 sample jobs from the Greenhouse adapter for sanity-checking field mapping."""

import asyncio

from app.crawlers.adapters.greenhouse import GreenhouseAdapter


async def main() -> None:
    async with GreenhouseAdapter("greenhouse") as ad:
        jobs = await ad.discover_jobs()
    print(f"Total jobs: {len(jobs)}\n")
    for job in jobs[:2]:
        print("title:", job.title)
        print("company:", job.company)
        print("location:", job.location)
        print("remote:", job.remote)
        print("external_job_id:", job.external_job_id)
        print("apply_url:", job.apply_url)
        print("description length:", len(job.description), "chars")
        print("skills:", job.skills[:8])
        print("---")


if __name__ == "__main__":
    asyncio.run(main())