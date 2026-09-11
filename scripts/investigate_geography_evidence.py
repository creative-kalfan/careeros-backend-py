"""Read-only investigation of geographic evidence (task §3, §8, §9).

Examines what deterministic evidence exists inside the DB rows for
UNKNOWN / AMBIGUOUS jobs (location value, title, remote flag) so we can
decide — conservatively — whether any would be re-classified.

No writes. Outputs:
  - unknown/ambiguous rows (source, company, location, title, remote)
  - distinct raw location strings across ALL active jobs (to see what the
    Greenhouse board exposes)
"""

from __future__ import annotations

import json
import os
from collections import Counter

try:
    from dotenv import load_dotenv

    load_dotenv(".env")
except Exception:  # pragma: no cover
    pass

from app.db.supabase import get_service_client
from app.services.jobs.india_geography import (
    AMBIGUOUS,
    UNKNOWN,
    classify_india_relevance,
)


def _fetch_all(client, is_active):
    rows = []
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
    client = get_service_client()
    rows = _fetch_all(client, True)

    lines: list[str] = []
    unknown_rows = []
    ambiguous_rows = []
    location_counter: Counter[str] = Counter()
    empty_location = 0
    for row in rows:
        loc = row.get("location")
        label = classify_india_relevance(loc, row.get("remote"))
        location_counter[str(loc)] += 1
        if not loc:
            empty_location += 1
        if label == UNKNOWN:
            unknown_rows.append(row)
        elif label == AMBIGUOUS:
            ambiguous_rows.append(row)

    lines.append(f"total={len(rows)} empty_location={empty_location} unknown={len(unknown_rows)} ambiguous={len(ambiguous_rows)}")

    lines.append("\n===== DISTINCT LOCATION VALUES (count>=1) =====")
    for value, count in location_counter.most_common():
        lines.append(f"{count:5d}  {value!r}")

    lines.append(f"\n===== UNKNOWN ROWS ({len(unknown_rows)}) — provider/company/location/title/remote =====")
    for row in unknown_rows[:120]:
        lines.append(
            f"{str(row.get('source_platform')):14s} | {str(row.get('company')):16s} | "
            f"{str(row.get('location'))!r:40s} | remote={row.get('remote')} | {str(row.get('title'))[:70]}"
        )

    lines.append(f"\n===== AMBIGUOUS ROWS ({len(ambiguous_rows)}) =====")
    for row in ambiguous_rows[:40]:
        lines.append(
            f"{str(row.get('source_platform')):14s} | {str(row.get('company')):16s} | "
            f"{str(row.get('location'))!r:40s} | remote={row.get('remote')} | {str(row.get('title'))[:70]}"
        )

    out = "\n".join(lines)
    with open("_geo_evidence.txt", "w", encoding="utf-8") as fh:
        fh.write(out)
    print("written")


if __name__ == "__main__":
    main()