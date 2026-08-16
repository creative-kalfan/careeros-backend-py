"""Port of the TypeScript DeadlineExtractor test suite (deadline-extractor.test.ts).

The same 19 inputs are reused. Because the Python port returns a ``datetime.date``
(instead of the TS raw matched string), expected values are expressed as dates.
The "return None rather than guess" cases are preserved exactly.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.parsing.deadline_extractor import extract_deadline


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        # --- Extract cases ---
        (
            "We're hiring a Senior Engineer. Apply by 2024-12-15 to be considered.",
            date(2024, 12, 15),
        ),
        (
            "Join our team! Apply by January 15, 2025 for priority consideration.",
            date(2025, 1, 15),
        ),
        (
            "Apply by Jan 15, 2025. Late applications will not be reviewed.",
            date(2025, 1, 15),
        ),
        (
            "Last date to apply is 2024-11-30. Please submit before then.",
            date(2024, 11, 30),
        ),
        (
            "Position: Backend Engineer\nDeadline: 2024-10-31\nLocation: Remote",
            date(2024, 10, 31),
        ),
        (
            "The deadline is March 1, 2025. Don't miss it!",
            date(2025, 3, 1),
        ),
        (
            "Applications close on February 28, 2025. Apply now!",
            date(2025, 2, 28),
        ),
        (
            "Applications close 2025-02-28. No exceptions.",
            date(2025, 2, 28),
        ),
        (
            "This position closes on December 20, 2024.",
            date(2024, 12, 20),
        ),
        (
            "Job Title: Product Manager\nApplication Deadline: 2025-01-10\nDepartment: Product",
            date(2025, 1, 10),
        ),
        (
            "Apply by 15 January 2025 for full consideration.",
            date(2025, 1, 15),
        ),
        (
            "Apply by 01/15/2025.",
            date(2025, 1, 15),
        ),
        # --- Null cases (no deadline language) ---
        (
            "We're looking for a Senior Software Engineer with 5+ years of experience in React, Node.js, and AWS. You'll be building scalable backend services and working with a talented team.",
            None,
        ),
        ("", None),
        (None, None),
        # "deadline" appears but not as a trigger pattern (e.g. "no deadline")
        (
            "There is no deadline for this position. We accept applications year-round.",
            None,
        ),
        # trigger phrase has no date following
        ("Apply by sending your resume to careers@company.com.", None),
        # vague relative dates like 'this Friday'
        ("Apply by this Friday for priority review.", None),
        # description with just posted date mentioned
        (
            "Posted on January 5, 2025. We're hiring a Data Scientist to join our ML team.",
            None,
        ),
    ],
)
def test_extract_deadline(description, expected):
    assert extract_deadline(description) == expected