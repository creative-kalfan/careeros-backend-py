"""Read-only India coverage baseline measurement (task §2, §4, §16, §18).

Fetches the current jobs table (no writes) and produces a complete geography
+ provider + company + role + city breakdown plus the India-first KPIs:

    total active jobs / India / foreign / ambiguous / unknown
    India % / foreign % / unknown %
    jobs by provider, India jobs by provider, foreign jobs by provider,
    unknown jobs by provider, India share by provider
    jobs by company, India jobs by company
    jobs by target role, India jobs by target role
    India jobs by city

The report is written to a timestamped JSON file and printed as a table so the
668-job baseline is preserved before any ingestion change is made.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Optional

try:
    from dotenv import load_dotenv

    load_dotenv(".env")
except Exception:  # pragma: no cover
    pass

from app.db.supabase import get_service_client
from app.services.jobs.india_geography import INDIA, classify_india_relevance
from app.parsing.role_classifier import classify

# Target-role buckets mirrored from ingestion_validation (substring matching).
TARGET_ROLE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "analytics": ("data analyst", "analytics", "bi analyst", "business analyst", "reporting analyst"),
    "data_engineering": ("data engineer", "analytics engineer", "etl", "data warehouse"),
    "ai_ml": ("machine learning", "ai engineer", "data scientist", "generative ai", "ml engineer"),
    "backend": ("backend", "python", "java backend", "api developer"),
    "sap": ("sap", "abap", "hana", "sap bw"),
}


def _target_role_bucket(title: str) -> Optional[str]:
    """Return the first target-role bucket matching the title, else None."""
    lowered = (title or "").lower()
    for bucket, keywords in TARGET_ROLE_KEYWORDS.items():
        if any(k in lowered for k in keywords):
            return bucket
    return None
def _indian_city_of(location: Optional[str]) -> str:
    """Best-known Indian city label for a location (deterministic)."""
    lowered = (location or "").lower()
    order = (
        ("bengaluru", "Bengaluru"), ("bangalore", "Bengaluru"),
        ("hyderabad", "Hyderabad"), ("chennai", "Chennai"),
        ("mumbai", "Mumbai"), ("pune", "Pune"),
        ("delhi", "Delhi NCR"), ("gurugram", "Gurugram"), ("gurgaon", "Gurugram"),
        ("noida", "Noida"), ("kolkata", "Kolkata"), ("ahmedabad", "Ahmedabad"),
        ("kochi", "Kochi"), ("jaipur", "Jaipur"), ("chandigarh", "Chandigarh"),
        ("coimbatore", "Coimbatore"), ("mohali", "Mohali"), ("dehradun", "Dehradun"),
        ("ajmer", "Ajmer"), ("udaipur", "Udaipur"), ("indore", "Indore"),
    )
    for token, label in order:
        if token in lowered:
            return label
    return "India (unspecified)"


def _fetch_all(client: Any, is_active: bool) -> list[dict[str, Any]]:
    """Fetch all rows for one is_active flag in bounded PostgREST chunks."""
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        res = client.table("jobs").select("*").eq("is_active", is_active).range(offset, offset + 999).execute()
        chunk = res.data or []
        if not chunk:
            break
        rows.extend(chunk)
        if len(chunk) < 1000:
            break
        offset += 1000
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only India coverage baseline.")
    parser.add_argument("--json", default="", help="Output JSON path (default: india_coverage_baseline.json)")
    args = parser.parse_args()

    client = get_service_client()
    rows = _fetch_all(client, True)
    inactive = _fetch_all(client, False)

    total = len(rows)
    india = foreign = ambiguous = unknown = 0
    by_provider: dict[str, dict[str, int]] = {}
    by_company: Counter[str] = Counter()
    india_by_company: Counter[str] = Counter()
    india_by_role: Counter[str] = Counter()
    by_target_role: Counter[str] = Counter()
    india_by_target_role: Counter[str] = Counter()
    india_by_city: Counter[str] = Counter()

    for row in rows:
        location = row.get("location")
        remote = row.get("remote")
        label = classify_india_relevance(location, remote)
        if label == INDIA:
            india += 1
            india_by_city[_indian_city_of(location)] += 1
        elif label == "FOREIGN":
            foreign += 1
        elif label == "AMBIGUOUS":
            ambiguous += 1
        else:
            unknown += 1

        provider = str(row.get("source_platform") or row.get("source") or "unknown")
        bucket = by_provider.setdefault(provider, {"total": 0, "india": 0, "foreign": 0, "ambiguous": 0, "unknown": 0})
        bucket["total"] += 1
        bucket[{"INDIA": "india", "FOREIGN": "foreign", "AMBIGUOUS": "ambiguous"}.get(label, "unknown")] += 1

        company = str(row.get("company") or "unknown")
        by_company[company] += 1
        if label == INDIA:
            india_by_company[company] += 1

        role = str(row.get("role_category") or classify(str(row.get("title") or "")) or "unknown")
        if label == INDIA:
            india_by_role[role] += 1

        target_role = _target_role_bucket(str(row.get("title") or ""))
        if target_role:
            by_target_role[target_role] += 1
            if label == INDIA:
                india_by_target_role[target_role] += 1

    india_pct = round(100.0 * india / total, 1) if total else 0.0
    foreign_pct = round(100.0 * foreign / total, 1) if total else 0.0
    unknown_pct = round(100.0 * unknown / total, 1) if total else 0.0

    provider_stats: dict[str, Any] = {}
    for provider, b in sorted(by_provider.items(), key=lambda kv: kv[1]["india"], reverse=True):
        provider_stats[provider] = {
            **b,
            "india_pct": round(100.0 * b["india"] / b["total"], 1) if b["total"] else 0.0,
        }

    report = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "totals": {
            "total_active_jobs": total,
            "inactive_jobs": len(inactive),
            "india": india,
            "foreign": foreign,
            "ambiguous": ambiguous,
            "unknown": unknown,
            "india_pct": india_pct,
            "foreign_pct": foreign_pct,
            "unknown_pct": unknown_pct,
        },
        "by_provider": provider_stats,
        "by_company": dict(by_company.most_common()),
        "india_by_company": dict(india_by_company.most_common()),
        "india_by_role": dict(india_by_role.most_common()),
        "by_target_role": dict(by_target_role.most_common()),
        "india_by_target_role": dict(india_by_target_role.most_common()),
        "india_by_city": dict(india_by_city.most_common()),
    }

    out_path = args.json or "india_coverage_baseline.json"
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=str)
    print(json.dumps(report, indent=2, default=str))

    print("\n--- Summary ---")
    print(f"total active jobs : {total}")
    print(f"India             : {india} ({india_pct}%)")
    print(f"foreign           : {foreign} ({foreign_pct}%)")
    print(f"ambiguous         : {ambiguous}")
    print(f"unknown           : {unknown} ({unknown_pct}%)")
    print(f"baseline written to: {os.path.abspath(out_path)}")


if __name__ == "__main__":
    main()