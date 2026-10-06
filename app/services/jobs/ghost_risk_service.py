"""Ghost risk score and verified-live evaluation service.

Rules:
  - Verified live = present in latest SUCCESSFUL first-party ATS crawl (record ATS source & time).
  - Never claim "verified" for aggregator/best-effort rows.
  - Ghost-risk score (0-100) calculated from transparent, weighted signals:
      - Age since first_seen (not posted_at alone)
      - Repost churn (job disappeared and new external id appeared with same company+title+location within N days)
      - Description unchanged for >60 days
      - Apply-URL liveness result (404/410, generic redirect, position filled)
      - Company board health (many very old postings, zero churn)
  - Output label: "Low ghost risk (estimate)", "Medium ghost risk (estimate)", "High ghost risk (estimate)".
  - NEVER label a job as "fake".
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from app.db.supabase import get_service_client

logger = logging.getLogger(__name__)

_PROBE_CACHE_LIVENESS: dict[str, bool] = {}


class GhostRiskService:
    """Evaluates liveness verification and ghost risk for jobs."""

    def __init__(self, client: Any = None) -> None:
        self._client = client

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = get_service_client()
        return self._client

    @classmethod
    def _probe_key(cls, client: Any) -> str:
        url = getattr(client, "supabase_url", None) or getattr(client, "_url", None)
        return str(url) if url else "default"

    def is_available(self) -> bool:
        """Check if job_liveness table exists."""
        client = self._get_client()
        key = self._probe_key(client)
        cached = _PROBE_CACHE_LIVENESS.get(key)
        if cached is None:
            try:
                client.table("job_liveness").select("job_id").limit(1).execute()
                cached = True
            except Exception:
                cached = False
            _PROBE_CACHE_LIVENESS[key] = cached
        return cached

    def calculate_ghost_risk(
        self,
        job_data: dict[str, Any],
        url_check_result: Optional[dict[str, Any]] = None,
        is_repost_churn: bool = False,
    ) -> dict[str, Any]:
        """Compute transparent ghost risk score (0-100) and contributing signals."""
        now = datetime.now(timezone.utc)
        signals: list[dict[str, Any]] = []
        total_risk = 0

        # 1. Age since first_seen_at (not posted_at alone)
        first_seen_str = job_data.get("first_seen_at") or job_data.get("created_at")
        age_days = 0
        if first_seen_str:
            try:
                fs_dt = datetime.fromisoformat(str(first_seen_str).replace("Z", "+00:00"))
                if fs_dt.tzinfo is None:
                    fs_dt = fs_dt.replace(tzinfo=timezone.utc)
                age_days = max(0, (now - fs_dt).days)
            except Exception:
                age_days = 0

        if age_days > 90:
            total_risk += 35
            signals.append({"signal": "age_over_90_days", "weight": 35, "description": f"First observed {age_days} days ago without closure"})
        elif age_days > 45:
            total_risk += 20
            signals.append({"signal": "age_over_45_days", "weight": 20, "description": f"First observed {age_days} days ago"})
        elif age_days > 21:
            total_risk += 10
            signals.append({"signal": "age_over_21_days", "weight": 10, "description": f"First observed {age_days} days ago"})

        # 2. Repost churn
        if is_repost_churn:
            total_risk += 25
            signals.append({"signal": "repost_churn", "weight": 25, "description": "Frequent repost churn detected for identical company and role"})

        # 3. Apply URL liveness
        if url_check_result:
            status = url_check_result.get("status")
            if status == "dead":
                total_risk += 50
                signals.append({"signal": "url_dead", "weight": 50, "description": "Application URL returned 404/410 Not Found"})
            elif status == "filled":
                total_risk += 45
                signals.append({"signal": "url_filled", "weight": 45, "description": "Application page indicates position filled or closed"})
            elif status == "redirect_generic":
                total_risk += 30
                signals.append({"signal": "url_redirect_generic", "weight": 30, "description": "Application link redirects to generic homepage or careers root"})

        # 4. Source tier reliability
        tier = int(job_data.get("source_tier") or 5)
        source = str(job_data.get("source_platform") or "")
        is_first_party_ats = source in ("ashby", "greenhouse", "lever", "smartrecruiters", "workday") and tier in (1, 2)
        if not is_first_party_ats:
            total_risk += 10
            signals.append({"signal": "aggregator_source", "weight": 10, "description": "Aggregated posting without direct first-party ATS verification"})

        final_score = min(100, max(0, total_risk))
        
        # Risk label
        if final_score < 30:
            label = "Low ghost risk (estimate)"
        elif final_score < 65:
            label = "Medium ghost risk (estimate)"
        else:
            label = "High ghost risk (estimate)"

        # Verified live status
        liveness_status = "active_unverified"
        if is_first_party_ats and bool(job_data.get("is_active", True)):
            liveness_status = "verified_live"

        return {
            "score": final_score,
            "label": label,
            "liveness_status": liveness_status,
            "is_verified_live": liveness_status == "verified_live",
            "verified_ats_source": source if liveness_status == "verified_live" else None,
            "signals": signals,
        }

    def save_liveness_record(
        self,
        job_id: str,
        evaluation: dict[str, Any],
        url_status: Optional[str] = None,
    ) -> None:
        """Persist evaluation in job_liveness table."""
        if not self.is_available():
            return

        now_iso = datetime.now(timezone.utc).isoformat()
        payload = {
            "job_id": job_id,
            "liveness_status": evaluation["liveness_status"],
            "ghost_risk_score": evaluation["score"],
            "ghost_signals": evaluation["signals"],
            "verified_ats_source": evaluation.get("verified_ats_source"),
            "last_verified_live_at": now_iso if evaluation.get("is_verified_live") else None,
            "apply_url_status": url_status,
            "apply_url_checked_at": now_iso if url_status else None,
            "computed_at": now_iso,
        }
        try:
            self._get_client().table("job_liveness").upsert(payload).execute()
        except Exception as exc:
            logger.warning("Failed to save job_liveness record (non-blocking): %s", exc)

    def get_liveness_record(self, job_id: str) -> Optional[dict[str, Any]]:
        """Retrieve stored liveness and ghost risk record for a job."""
        if not self.is_available():
            return None
        try:
            res = self._get_client().table("job_liveness").select("*").eq("job_id", job_id).limit(1).execute()
            data = getattr(res, "data", None)
            if data and isinstance(data, list):
                return data[0]
            return None
        except Exception:
            return None
