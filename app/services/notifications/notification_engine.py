"""Notification engine: deterministic domain logic for notifications.

Pure business logic — no database or HTTP access. Mirrors the intended
behavior of the legacy TypeScript NotificationTemplateService /
NotificationPreferenceService, translated to the Python architecture.

Only notification types supported by the existing schema and current
CareerOS requirements are implemented:
- HIGH_MATCH_RECOMMENDATION (gated by user high_match_threshold preference)
- NEW_RECOMMENDATION_AVAILABLE (summary after a recommendation refresh)
Other frontend-known types (ATS_SCORE_IMPROVED, APPLICATION_STATUS_UPDATED,
etc.) can be added later via :func:`build_template` as their producer
services come online.
"""

from __future__ import annotations

from typing import Any, Optional

# Defaults aligned with the legacy migration's column defaults and the
# frontend NotificationPreferenceRecord semantics.
DEFAULT_PREFERENCES: dict[str, Any] = {
    "email_enabled": False,
    "in_app_enabled": True,
    "push_enabled": False,
    "high_match_threshold": 85,
    "daily_digest": False,
    "weekly_digest": False,
    "quiet_hours": None,
}

VALID_PREFERENCE_FIELDS = frozenset(
    {
        "email_enabled",
        "in_app_enabled",
        "push_enabled",
        "high_match_threshold",
        "daily_digest",
        "weekly_digest",
        "quiet_hours",
    }
)


class NotificationEngine:
    """Deterministic templates and preference gates for notifications."""

    def build_high_match_recommendation(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Build title/message/priority for a high-match recommendation."""
        score = int(payload.get("score") or 0)
        job_title = payload.get("jobTitle") or "A job"
        company_name = payload.get("companyName") or ""
        return {
            "type": "HIGH_MATCH_RECOMMENDATION",
            "title": "New high-match job recommendation",
            "message": f"{job_title} at {company_name} scored {score}% for your profile.".replace(" at  ", " "),
            "priority": "critical" if score >= 90 else "high",
            "payload_json": payload,
        }

    def build_new_recommendation_available(self, top_match_count: int) -> dict[str, Any]:
        """Build the summary notification emitted after a refresh."""
        return {
            "type": "NEW_RECOMMENDATION_AVAILABLE",
            "title": "New recommendations available",
            "message": (
                f"You have {top_match_count} new recommendation"
                f"{'' if top_match_count == 1 else 's'} ready to review."
            ),
            "priority": "high" if top_match_count >= 5 else "medium",
            "payload_json": {"topMatchCount": top_match_count},
        }

    def build_generic(
        self,
        type: str,
        title: str,
        message: str,
        payload: Optional[dict[str, Any]] = None,
        priority: str = "medium",
    ) -> dict[str, Any]:
        """Generic template for internal producers (future hooks)."""
        return {
            "type": type,
            "title": title,
            "message": message,
            "priority": priority,
            "payload_json": payload or {},
        }

    @staticmethod
    def should_notify_high_match(preferences: dict[str, Any], score: int) -> bool:
        """Gate on in-app delivery being enabled and threshold preference."""
        if not preferences.get("in_app_enabled", True):
            return False
        threshold = preferences.get("high_match_threshold")
        if threshold is None:
            threshold = DEFAULT_PREFERENCES["high_match_threshold"]
        try:
            threshold = int(threshold)
        except (TypeError, ValueError):
            threshold = DEFAULT_PREFERENCES["high_match_threshold"]
        return score >= threshold

    @staticmethod
    def merge_preferences(updates: dict[str, Any]) -> dict[str, Any]:
        """Filter an update payload down to valid preference fields."""
        return {k: v for k, v in updates.items() if k in VALID_PREFERENCE_FIELDS}
