"""Calibration script for Ghost Risk score distribution.

Evaluates distribution on synthetic or production-like sample.
Flags a warning if >40% of jobs land in High ghost risk.
"""

from __future__ import annotations

import sys
from app.services.jobs.ghost_risk_service import GhostRiskService


def run_calibration():
    service = GhostRiskService()
    
    # Representative sample of job profiles
    test_samples = [
        {"source_platform": "greenhouse", "source_tier": 2, "is_active": True, "first_seen_at": "2026-10-01"},
        {"source_platform": "ashby", "source_tier": 2, "is_active": True, "first_seen_at": "2026-09-20"},
        {"source_platform": "workday", "source_tier": 2, "is_active": True, "first_seen_at": "2026-09-01"},
        {"source_platform": "adzuna", "source_tier": 5, "is_active": True, "first_seen_at": "2026-09-10"},
        {"source_platform": "naukri", "source_tier": 5, "is_active": True, "first_seen_at": "2026-08-01"},
        {"source_platform": "jobspy", "source_tier": 5, "is_active": True, "first_seen_at": "2026-07-01"},
    ]

    distribution = {"Low": 0, "Medium": 0, "High": 0}
    scores = []

    for job in test_samples:
        eval_res = service.calculate_ghost_risk(job)
        score = eval_res["score"]
        scores.append(score)
        if "Low" in eval_res["label"]:
            distribution["Low"] += 1
        elif "Medium" in eval_res["label"]:
            distribution["Medium"] += 1
        else:
            distribution["High"] += 1

    total = len(test_samples)
    print("=== Ghost Risk Calibration Report ===")
    print(f"Total Evaluated: {total}")
    for cat, count in distribution.items():
        pct = (count / total) * 100
        print(f"  {cat}: {count} ({pct:.1f}%)")

    high_pct = (distribution["High"] / total) * 100
    if high_pct > 40:
        print(f"WARNING: High ghost risk proportion ({high_pct:.1f}%) exceeds 40% threshold! Calibration needed.")
        return 1
    else:
        print("PASS: Ghost risk distribution is well-calibrated (High <= 40%).")
        return 0


if __name__ == "__main__":
    sys.exit(run_calibration())
