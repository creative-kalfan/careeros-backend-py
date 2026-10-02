"""Generate report of Firecrawl targets whose company has a direct ATS board."""

from __future__ import annotations

import json
from app.crawlers.crawl_registry import FIRECRAWL_TARGETS, ATS_TARGETS
from app.services.jobs.jobspy_strategy import _normalize_company_token


def generate_overlap_report() -> dict[str, list[dict[str, str]]]:
    ats_by_company: dict[str, list[dict[str, str]]] = {}
    for target in ATS_TARGETS:
        if target.company:
            token = _normalize_company_token(target.company)
            ats_by_company.setdefault(token, []).append({
                "source": target.source,
                "slug": target.slug,
                "company": target.company,
                "url": target.url,
            })

    overlaps: list[dict[str, str]] = []
    exclusive: list[dict[str, str]] = []

    for fc in FIRECRAWL_TARGETS:
        token = _normalize_company_token(fc.company)
        matched_ats = ats_by_company.get(token, [])
        if matched_ats:
            for ats in matched_ats:
                overlaps.append({
                    "company": fc.company,
                    "firecrawl_slug": fc.slug,
                    "firecrawl_url": fc.url,
                    "ats_source": ats["source"],
                    "ats_slug": ats["slug"],
                    "ats_url": ats["url"],
                })
        else:
            exclusive.append({
                "company": fc.company,
                "firecrawl_slug": fc.slug,
                "firecrawl_url": fc.url,
            })

    report = {
        "overlapping_targets": overlaps,
        "exclusive_firecrawl_targets": exclusive,
    }
    return report


if __name__ == "__main__":
    report = generate_overlap_report()
    out_path = "firecrawl_ats_overlap_report.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"Report written to {out_path}: {len(report['overlapping_targets'])} overlapping, {len(report['exclusive_firecrawl_targets'])} exclusive.")
