"""Universal content prioritization (Stage 5a of the tailoring pipeline).

No fixed assumptions ("always include projects", "always put skills first").
Every candidate content item receives a value score::

    content_value = jd_relevance + evidence_strength + impact
                    + recency + uniqueness - redundancy

The tailoring and layout stages consume these scores to decide ordering,
emphasis, and — only under a page constraint — what to trim first.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.services.optimization.evidence_matcher import MatchReport
from app.services.optimization.jd_requirements import normalize_key

_TOKEN_RE = re.compile(r"[a-z0-9+#./-]+", re.IGNORECASE)


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text or "") if len(t) > 2}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _jd_relevance_for_text(text: str, report: MatchReport) -> float:
    """0..3 — strongest JD requirement overlap with this text."""
    text_key = set(normalize_key(text).split())
    if not text_key:
        return 0.0
    best = 0.0
    lowered = (text or "").lower()
    for m in report.matches:
        req_key = set(m.requirement.normalized_key.split())
        if not req_key:
            continue
        overlap = len(text_key & req_key) / max(len(req_key), 1)
        importance_boost = {"high": 1.0, "medium": 0.7, "low": 0.4}.get(
            m.requirement.importance, 0.7
        )
        # Direct substring evidence is a strong relevance signal.
        if m.requirement.text.lower() in lowered or lowered in m.requirement.text.lower():
            overlap = max(overlap, 0.85)
        score = overlap * 3.0 * importance_boost
        # Unclaimable requirements contribute nothing — surfacing them would
        # reward fabricating experience for irrelevant JDs.
        if not m.is_claimable:
            score = 0.0
        best = max(best, score)
    return round(min(best, 3.0), 3)


@dataclass
class ContentScore:
    item_id: str
    section: str
    text: str
    jd_relevance: float = 0.0
    evidence_strength: float = 0.0
    impact: float = 0.0
    recency: float = 0.0
    uniqueness: float = 0.0
    redundancy: float = 0.0
    total: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "item_id": self.item_id,
            "section": self.section,
            "jd_relevance": self.jd_relevance,
            "evidence_strength": self.evidence_strength,
            "impact": self.impact,
            "recency": self.recency,
            "uniqueness": self.uniqueness,
            "redundancy": self.redundancy,
            "total": round(self.total, 3),
        }


def _impact_score(text: str, has_metric: bool, action_strength: float) -> float:
    """0..2 — measurable impact + strong delivery language."""
    score = 0.6  # every truthful claim carries baseline value
    if has_metric:
        score += 0.7
    score += action_strength * 0.5
    n = len(text or "")
    if 60 <= n <= 240:
        score += 0.2
    return round(min(score, 2.0), 3)


def score_items(
    items: List[Dict[str, Any]],
    report: MatchReport,
    recency_weights: Optional[List[float]] = None,
) -> List[ContentScore]:
    """Score arbitrary content items (bullets, skills, entries).

    Each item: {"id": str, "section": str, "text": str,
    "has_metric": bool, "action_strength": float}.
    Recency weights are positional (index 0 = most recent = 1.0); when
    omitted every item gets a neutral 0.5.
    """
    token_sets = [_tokens(i.get("text", "")) for i in items]
    scores: List[ContentScore] = []
    for idx, item in enumerate(items):
        text = item.get("text", "")
        jd_rel = _jd_relevance_for_text(text, report)
        ev = 0.7 + 0.3 * float(item.get("action_strength", 0.5))
        if item.get("has_metric"):
            ev = min(ev + 0.2, 1.5)
        ev = round(min(ev * 1.33, 2.0), 3)  # scale to 0..2 band
        imp = _impact_score(text, bool(item.get("has_metric")), float(item.get("action_strength", 0.5)))
        rec = round(float(recency_weights[idx]) if recency_weights and idx < len(recency_weights) else 0.5, 3)
        # Uniqueness / redundancy from pairwise token similarity.
        max_sim = 0.0
        for j, other in enumerate(token_sets):
            if j == idx:
                continue
            max_sim = max(max_sim, _jaccard(token_sets[idx], other))
        uniqueness = round(1.0 - max_sim, 3)
        redundancy = round(max_sim * 1.5, 3)
        total = jd_rel + ev + imp + rec + uniqueness - redundancy
        scores.append(
            ContentScore(
                item_id=str(item.get("id", f"item-{idx}")),
                section=str(item.get("section", "general")),
                text=text[:280],
                jd_relevance=jd_rel,
                evidence_strength=ev,
                impact=imp,
                recency=rec,
                uniqueness=uniqueness,
                redundancy=redundancy,
                total=round(total, 3),
            )
        )
    return scores


def rank_items(scores: List[ContentScore]) -> List[ContentScore]:
    """Highest value first (stable — ties keep source order)."""
    return sorted(scores, key=lambda s: s.total, reverse=True)


def recency_weights_for_entries(count: int, decay: float = 0.85) -> List[float]:
    """Most-recent-first decay: [1.0, 0.85, 0.72, ...]."""
    return [round(decay**i, 3) for i in range(count)]
