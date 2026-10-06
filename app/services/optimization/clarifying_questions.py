"""Clarifying questions generator and answer recorder (Ask-don't-invent)."""

from __future__ import annotations

from typing import Any, Optional
from uuid import uuid4
from pydantic import BaseModel, Field


class ClarifyingQuestion(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    bullet_ref: str
    question: str
    expected_type: str = "metric"  # metric | timeframe | scale | tool


def generate_clarifying_question_for_violation(
    bullet_ref: str,
    unsupported_figure: str,
    context_role: Optional[str] = None,
) -> ClarifyingQuestion:
    """Ask candidate for real metrics when an ungrounded claim was rejected."""
    return ClarifyingQuestion(
        bullet_ref=bullet_ref,
        question=f"What was the actual measured metric or impact for this achievement instead of {unsupported_figure}?",
        expected_type="metric",
    )
