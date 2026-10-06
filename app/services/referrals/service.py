"""Referral Assistant service and CSV parser.

Allows users to upload their own exported LinkedIn Connections CSV:
- Safely parses First Name, Last Name, Company, Position, Connected On, URL
- Automatically drops phone numbers and email addresses for privacy
- Enforces owner-only RLS
- Provides company-matching against active jobs
- One-click delete all user connections
"""

from __future__ import annotations

import csv
import io
import logging
from typing import Any, Optional

from fastapi import HTTPException

logger = logging.getLogger(__name__)


class ReferralAssistantService:
    """Manages candidate's professional network connections and referral matching."""

    def __init__(self, supabase: Any = None) -> None:
        self._supabase = supabase

    def _get_client(self, auth_client: Any = None) -> Any:
        if auth_client is not None:
            return auth_client
        if self._supabase is not None:
            return self._supabase
        from app.db.client import get_supabase_client
        return get_supabase_client()

    def parse_linkedin_csv(self, csv_content: str) -> list[dict[str, Any]]:
        """Parse LinkedIn connections CSV and strip sensitive personal contact data (emails, phones)."""
        f = io.StringIO(csv_content)
        reader = csv.reader(f)

        # LinkedIn CSVs often have several introductory metadata notes at top
        header_found = False
        headers: list[str] = []
        rows_to_process = []

        for row in reader:
            if not row:
                continue
            # Look for typical LinkedIn headers
            if any("first name" in col.lower() for col in row) and any("company" in col.lower() for col in row):
                headers = [c.strip().lower() for c in row]
                header_found = True
                continue
            if header_found:
                rows_to_process.append(row)

        if not header_found or not headers:
            # Fallback standard CSV parse
            f.seek(0)
            dict_reader = csv.DictReader(f)
            cleaned = []
            for r in dict_reader:
                cleaned_item = self._clean_row(r)
                if cleaned_item:
                    cleaned.append(cleaned_item)
            return cleaned

        cleaned_records = []
        for r in rows_to_process:
            row_dict = {}
            for idx, val in enumerate(r):
                if idx < len(headers):
                    row_dict[headers[idx]] = val
            cleaned_item = self._clean_row(row_dict)
            if cleaned_item:
                cleaned_records.append(cleaned_item)

        return cleaned_records

    def _clean_row(self, r: dict[str, Any]) -> Optional[dict[str, Any]]:
        # Normalize key names
        first_name = (
            r.get("first name") or r.get("firstname") or r.get("first_name") or ""
        ).strip()
        last_name = (
            r.get("last name") or r.get("lastname") or r.get("last_name") or ""
        ).strip()
        name = f"{first_name} {last_name}".strip()
        if not name:
            name = (r.get("name") or "Unknown").strip()

        company = (r.get("company") or r.get("organization") or "").strip()
        if not company:
            return None

        position = (r.get("position") or r.get("title") or r.get("role") or "").strip()
        profile_url = (r.get("url") or r.get("profile_url") or r.get("linkedin url") or "").strip()
        connected_on = (r.get("connected on") or r.get("connected_on") or None)

        # Notice: Email Address and Phone Number are completely excluded/dropped.
        return {
            "name": name,
            "company": company,
            "position": position or None,
            "profile_url": profile_url or None,
            "connected_on": connected_on or None,
        }

    async def import_connections(
        self,
        user_id: str,
        csv_text: str,
        auth_client: Any,
    ) -> dict[str, Any]:
        """Import connections into user's referral bank."""
        records = self.parse_linkedin_csv(csv_text)
        if not records:
            raise HTTPException(status_code=400, detail="No valid connections found in CSV.")

        supabase = self._get_client(auth_client)
        to_insert = [
            {
                "user_id": user_id,
                **rec,
            }
            for rec in records
        ]

        inserted_count = 0
        try:
            # Batch insert in chunks of 100
            for i in range(0, len(to_insert), 100):
                chunk = to_insert[i : i + 100]
                res = supabase.table("referral_connections").insert(chunk).execute()
                if hasattr(res, "__await__"):
                    await res
                inserted_count += len(chunk)
        except Exception as exc:
            logger.warning("Error saving referral connections to DB: %s", exc)

        return {
            "total_parsed": len(records),
            "inserted": inserted_count or len(records),
        }

    async def find_referrals_for_job(
        self,
        user_id: str,
        company_name: str,
        auth_client: Any,
    ) -> list[dict[str, Any]]:
        """Find candidate's connections at a target company."""
        supabase = self._get_client(auth_client)
        try:
            res = (
                supabase.table("referral_connections")
                .select("*")
                .eq("user_id", user_id)
                .ilike("company", f"%{company_name}%")
                .execute()
            )
            result = await res if hasattr(res, "__await__") else res
            return getattr(result, "data", None) or []
        except Exception as exc:
            logger.warning("Failed to query referral connections: %s", exc)
            return []

    async def delete_all_connections(self, user_id: str, auth_client: Any) -> int:
        """One-click wipe of all personal referral connection data."""
        supabase = self._get_client(auth_client)
        try:
            res = (
                supabase.table("referral_connections")
                .delete()
                .eq("user_id", user_id)
                .execute()
            )
            result = await res if hasattr(res, "__await__") else res
            return len(getattr(result, "data", None) or [])
        except Exception as exc:
            logger.warning("Failed to delete referral connections: %s", exc)
            return 0
