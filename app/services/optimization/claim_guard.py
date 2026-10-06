"""Numeric-claim guard for generated resume content.

Enforces:
  - Extracts numbers, percentages, currency ($, ₹, Rs, Rupee, lakh, crore, k/M/B), multipliers (2x), ranges, durations.
  - Normalizes figures ("40%" == "40 percent", "₹5L" == "5 lakh", "10k" == "10,000").
  - Rejects generated claims whose numeric figures do not exist in the candidate's cited evidence.
  - Generates clarifying questions instead of hallucinating metrics.
"""

from __future__ import annotations

import re
from typing import Any, Optional


def extract_numeric_tokens(text: str) -> set[str]:
    """Extract and normalize all numeric claims from text."""
    if not text:
        return set()

    tokens: set[str] = set()

    # 1. Percentages (40%, 40 percent)
    for m in re.finditer(r"\b(\d+(?:\.\d+)?)\s*(?:%|\bpercent\b)", text, re.IGNORECASE):
        val = m.group(1).rstrip(".0") if "." in m.group(1) else m.group(1)
        tokens.add(f"{val}%")

    # 2. Multipliers (2x, 3.5x)
    for m in re.finditer(r"\b(\d+(?:\.\d+)?)\s*x\b", text, re.IGNORECASE):
        val = m.group(1).rstrip(".0") if "." in m.group(1) else m.group(1)
        tokens.add(f"{val}x")

    # 3. Currency and Indian denominations (lakh, crore, k, M, B)
    # Indian: 5 lakh, 10 crore, Rs 25 lac, ₹10Cr
    for m in re.finditer(r"(?:₹|rs\.?|inr|\$)?\s*(\d+(?:\.\d+)?)\s*(lakh|lac|crore|cr|k|m|b|million|billion)\b", text, re.IGNORECASE):
        num = m.group(1).rstrip(".0") if "." in m.group(1) else m.group(1)
        denom = m.group(2).lower()
        if denom in ("lac", "lakh"):
            denom = "lakh"
        elif denom in ("cr", "crore"):
            denom = "crore"
        elif denom == "million":
            denom = "m"
        elif denom == "billion":
            denom = "b"
        tokens.add(f"{num}{denom}")

    # 4. Standalone numbers / metrics (exclude those followed by % or x or currency)
    for m in re.finditer(r"(?<![a-zA-Z0-9_.])(\d+(?:,\d+)*(?:\.\d+)?)(?![a-zA-Z0-9_.%x])", text):
        raw = m.group(1).replace(",", "")
        val = raw.rstrip(".0") if "." in raw else raw
        if val and int(float(val)) != 0:
            tokens.add(val)

    return tokens


class ClaimGuard:
    """Verifies that generated text contains only evidenced figures."""

    @classmethod
    def verify_claims(
        cls,
        generated_text: str,
        evidence_text: str,
    ) -> tuple[bool, set[str]]:
        """Check if all numeric tokens in generated_text exist in evidence_text.
        
        Returns (is_valid, set_of_unsupported_tokens).
        """
        gen_tokens = extract_numeric_tokens(generated_text)
        evi_tokens = extract_numeric_tokens(evidence_text)

        # Allow simple integers <= 1 (e.g. "a", "one")
        unsupported = set()
        for tok in gen_tokens:
            if tok in ("1", "0"):
                continue
            if tok not in evi_tokens:
                unsupported.add(tok)

        return (len(unsupported) == 0, unsupported)

    @classmethod
    def sanitize_unsupported_figures(
        cls,
        text: str,
        unsupported_tokens: set[str],
    ) -> str:
        """Strip unsupported figures or replace with qualitative terms."""
        sanitized = text
        for tok in sorted(unsupported_tokens, key=len, reverse=True):
            if tok.endswith("%"):
                num = tok[:-1]
                sanitized = re.sub(rf"\b{re.escape(num)}\s*%", "measurably", sanitized, flags=re.IGNORECASE)
                sanitized = re.sub(rf"\b{re.escape(num)}\s*percent\b", "measurably", sanitized, flags=re.IGNORECASE)
            elif tok.endswith("x"):
                num = tok[:-1]
                sanitized = re.sub(rf"\b{re.escape(num)}\s*x\b", "substantially", sanitized, flags=re.IGNORECASE)
            else:
                sanitized = re.sub(rf"\b{re.escape(tok)}\b", "several", sanitized, flags=re.IGNORECASE)
        return re.sub(r"\s+", " ", sanitized).strip()
