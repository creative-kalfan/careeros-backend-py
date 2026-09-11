"""Read-only: inactive jobs by provider + geography (for coverage analysis)."""

from __future__ import annotations
from collections import Counter

try:
    from dotenv import load_dotenv

    load_dotenv(".env")
except Exception:  # pragma: no cover
    pass

from app.db.supabase import get_service_client
from app.services.jobs.india_geography import classify_india_relevance


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
    rows = _fetch_all(client, False)
    lines: list[str] = []
    lines.append(f"inactive total={len(rows)}")
    by_provider = Counter(r.get("source_platform") or "none" for r in rows)
    lines.append("by_provider=" + json_dumps(dict(by_provider)))
    geo = Counter(classify_india_relevance(r.get("location")) for r in rows)
    lines.append("geo=" + json_dumps(dict(geo)))
    # Per-provider geography for the largest inactive providers.
    for provider in sorted(by_provider, key=lambda p: by_provider[p], reverse=True)[:8]:
        sub = [r for r in rows if (r.get("source_platform") or "none") == provider]
        g = Counter(classify_india_relevance(r.get("location")) for r in sub)
        lines.append(f"provider={provider}: {json_dumps(dict(g))}")
    with open("_inactive.txt", "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print("written")


def json_dumps(obj):
    import json

    return json.dumps(obj, default=str)


if __name__ == "__main__":
    main()