"""DeadlineExtractor

Extracts application deadlines from job description text using regex patterns.
Returns a ``datetime.date`` if a deadline is found, or ``None`` if no deadline
language is found — no guessing, no inference from posted_date + arbitrary
offset, and no coercion of vague relative dates.

This is a pure function port of the TypeScript
``services/parsing/DeadlineExtractor.ts``. The trigger phrases, date regexes,
search region, and "return None rather than guess" behavior are preserved
exactly. The only difference from the original is that we return a parsed
``datetime.date`` (instead of the raw matched string), per the requested
Python API. It performs no I/O.
"""

from __future__ import annotations

import re
from datetime import date

# Date patterns we recognize (order matters - more specific first):
# 1. ISO format: 2024-01-15, 2024/01/15
# 2. Month name formats: January 15, 2024 / Jan 15, 2024 / 15 January 2024 / 15 Jan 2024
# 3. Numeric US: 01/15/2024, 1/15/2024
# 4. Numeric EU: 15/01/2024, 15/1/2024
# 5. Relative: "this Friday", "end of week", "end of month" (returns None - too vague)
_DATE_REGEX = [
    # ISO: 2024-01-15 or 2024/01/15
    re.compile(
        r"\b(\d{4}[-/](?:0?[1-9]|1[0-2])[-/](?:0?[1-9]|[12]\d|3[01]))\b",
        re.IGNORECASE,
    ),
    # Month name first: January 15, 2024 / Jan 15, 2024 / January 15 / Jan 15
    re.compile(
        r"\b((?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s+(?:0?[1-9]|[12]\d|3[01])(?:,?\s+\d{4})?)\b",
        re.IGNORECASE,
    ),
    # Day first: 15 January 2024 / 15 Jan 2024 / 15 January
    re.compile(
        r"\b((?:0?[1-9]|[12]\d|3[01])\s+(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?(?:,?\s+\d{4})?)\b",
        re.IGNORECASE,
    ),
    # US numeric: 01/15/2024, 1/15/24
    re.compile(
        r"\b((?:0?[1-9]|1[0-2])\/(?:0?[1-9]|[12]\d|3[01])\/(?:\d{2}|\d{4}))\b"
    ),
    # EU numeric: 15/01/2024, 15/1/24
    re.compile(
        r"\b((?:0?[1-9]|[12]\d|3[01])\/(?:0?[1-9]|1[0-2])\/(?:\d{2}|\d{4}))\b"
    ),
]

# Trigger phrases that indicate a deadline follows.
# Each phrase is followed by an optional preposition (on, by, :, etc.)
# and then a date.
_DEADLINE_TRIGGERS = [
    # "apply by <date>"
    re.compile(r"apply\s+by\s+", re.IGNORECASE),
    # "last date to apply <date>" or "last date to apply is <date>"
    re.compile(r"last\s+date\s+to\s+apply\s+(?:is\s+)?", re.IGNORECASE),
    # "deadline: <date>" or "deadline is <date>"
    re.compile(r"deadline\s*[:\s]+(?:is\s+)?", re.IGNORECASE),
    # "applications close <date>" or "applications close on <date>"
    re.compile(r"applications?\s+close\s+(?:on\s+)?", re.IGNORECASE),
    # "closes on <date>"
    re.compile(r"closes?\s+on\s+", re.IGNORECASE),
    # "application deadline <date>" or "application deadline: <date>"
    re.compile(r"application\s+deadline\s*[:\s]+", re.IGNORECASE),
]

# datetime.strptime formats tried, in order, to parse a matched date word into
# a ``date``. US numeric is tried before EU numeric to match the TS ordering.
_PARSE_FORMATS = [
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%B %d, %Y",
    "%b %d, %Y",
    "%d %B %Y",
    "%d %b %Y",
    "%m/%d/%Y",
    "%m/%d/%y",
    "%d/%m/%Y",
    "%d/%m/%y",
]


def _parse_date_word(word: str) -> date | None:
    """Parse a matched date word into a ``datetime.date``.

    Returns ``None`` (rather than guessing) if the word cannot be parsed —
    this preserves the "return None rather than guess" behavior from the
    original for relative/vague or unparseable language.
    """
    from datetime import datetime

    cleaned = word.strip().rstrip(",")
    for fmt in _PARSE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    # Month-name forms without a year (e.g. "January 15") cannot be converted
    # to a concrete date without inventing a year — don't guess.
    return None


def extract_deadline(description: str | None) -> date | None:
    """Extract an application deadline from job description text.

    Returns a parsed ``datetime.date`` if a deadline is found, or ``None`` if
    no deadline pattern matches or the date cannot be parsed without guessing.
    """
    if not description:
        return None

    # Try each trigger phrase
    for trigger in _DEADLINE_TRIGGERS:
        trigger_match = trigger.search(description)
        if not trigger_match:
            continue

        # Get the text after the trigger phrase
        after_trigger = description[trigger_match.end():]

        # Look for a date in the text immediately following the trigger (within 100 chars)
        search_region = after_trigger[:100]

        for date_regex in _DATE_REGEX:
            date_match = date_regex.search(search_region)
            if date_match:
                parsed = _parse_date_word(date_match.group(1).strip())
                if parsed is not None:
                    return parsed
                # If the matched word couldn't be parsed to a concrete date,
                # keep scanning other patterns (don't guess).

    return None