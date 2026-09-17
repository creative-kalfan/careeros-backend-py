"""Deterministic Role Family classification and compatibility layer.

Enforces role-family boundaries before ranking to prevent cross-role
contamination (e.g. generic Software Engineer dominating SAP or Data Engineer).
"""

from __future__ import annotations

import re
from typing import Optional


class RoleFamily:
    ANALYTICS_BI = "ANALYTICS_BI"
    DATA_ENGINEERING = "DATA_ENGINEERING"
    BACKEND = "BACKEND"
    AI_ML = "AI_ML"
    SAP_ERP = "SAP_ERP"
    SOFTWARE_ENGINEERING = "SOFTWARE_ENGINEERING"
    DEVOPS_CLOUD = "DEVOPS_CLOUD"
    QA_TESTING = "QA_TESTING"
    PRODUCT_MANAGEMENT = "PRODUCT_MANAGEMENT"
    DESIGN = "DESIGN"
    CYBERSECURITY = "CYBERSECURITY"
    OTHER = "OTHER"


# Canonical mapping patterns for role families. Ordered by specificity.
# More specific patterns (SAP, AI/ML, Data Engineering, Analytics) precede generic SWE.
_ROLE_FAMILY_PATTERNS: list[tuple[str, list[str]]] = [
    (
        RoleFamily.SAP_ERP,
        [
            r"\bsap\b", r"\babap\b", r"\bfico\b", r"\bhana\b", r"\bbasis\b",
            r"\bsap\s+mm\b", r"\bsap\s+sd\b", r"\bsap\s+bw\b", r"\berp\s+consultant\b",
        ],
    ),
    (
        RoleFamily.AI_ML,
        [
            r"\bmachine\s+learning\b", r"\bml\s+engineer\b", r"\bai\s+engineer\b",
            r"\bapplied\s+scientist\b", r"\bresearch\s+scientist\b", r"\bnlp\b",
            r"\bcomputer\s+vision\b", r"\bdeep\s+learning\b", r"\bmlops\b",
            r"\bdata\s+scientist\b", r"\bdata\s+science\b", r"\bgenerative\s+ai\b",
            r"\bgenai\b", r"\bllm\b", r"\bai\s+platform\b",
        ],
    ),
    (
        RoleFamily.DATA_ENGINEERING,
        [
            r"\bdata\s+engineer\b", r"\bdata\s+engineering\b",
            r"\banalytics\s+engineer\b", r"\betl\s+engineer\b",
            r"\betl\s+developer\b", r"\bdata\s+platform\s+engineer\b",
            r"\bdata\s+infrastructure\s+engineer\b", r"\bbig\s+data\s+engineer\b",
            r"\bdata\s+warehouse\s+engineer\b", r"\bdata\s+pipeline\b",
            r"\bdatabase\s+engineer\b", r"\bdatabase\s+developer\b",
        ],
    ),
    (
        RoleFamily.ANALYTICS_BI,
        [
            r"\bdata\s+analyst\b", r"\bbusiness\s+analyst\b", r"\bbi\s+analyst\b",
            r"\bbi\s+developer\b", r"\bbusiness\s+intelligence\b",
            r"\breporting\s+analyst\b", r"\bproduct\s+analyst\b",
            r"\boperations\s+analyst\b", r"\bfinancial\s+analyst\b",
            r"\bmarketing\s+analyst\b", r"\bdata\s+analytics\b",
            r"\brisk\s+analyst\b", r"\bquantitative\s+analyst\b",
            r"\bmis\s+analyst\b", r"\bmis\s+executive\b",
        ],
    ),
    (
        RoleFamily.BACKEND,
        [
            r"\bback[-\s]?end\s+engineer\b", r"\bback[-\s]?end\s+developer\b",
            r"\bback[-\s]?end\s+software\s+engineer\b", r"\bapi\s+engineer\b",
            r"\bapi\s+developer\b", r"\bserver[-\s]?side\s+engineer\b",
            r"\bserver[-\s]?side\s+developer\b", r"\bpython\s+back[-\s]?end\b",
            r"\bjava\s+developer\b", r"\bgolang\s+developer\b",
            r"\bnode(?:\.js)?\s+developer\b", r"\bnode(?:\.js)?\s+backend\b",
        ],
    ),
    (
        RoleFamily.DEVOPS_CLOUD,
        [
            r"\bdevops\b", r"\bsite\s+reliability\b", r"\bsre\b",
            r"\bcloud\s+engineer\b", r"\bplatform\s+engineer\b",
            r"\binfrastructure\s+engineer\b", r"\bsysadmin\b",
        ],
    ),
    (
        RoleFamily.QA_TESTING,
        [
            r"\bqa\b", r"\bquality\s+assurance\b", r"\btest\s+engineer\b",
            r"\bautomation\s+engineer\b", r"\bsdet\b", r"\bsoftware\s+tester\b",
        ],
    ),
    (
        RoleFamily.PRODUCT_MANAGEMENT,
        [
            r"\bproduct\s+manager\b", r"\bproduct\s+owner\b", r"\btechnical\s+product\s+manager\b",
        ],
    ),
    (
        RoleFamily.DESIGN,
        [
            r"\bui\/ux\b", r"\bux\s+designer\b", r"\bui\s+designer\b",
            r"\bproduct\s+designer\b",
        ],
    ),
    (
        RoleFamily.CYBERSECURITY,
        [
            r"\bsecurity\s+engineer\b", r"\bcybersecurity\b", r"\binfosec\b",
            r"\bappsec\b",
        ],
    ),
    (
        RoleFamily.SOFTWARE_ENGINEERING,
        [
            r"\bsoftware\s+engineer\b", r"\bsoftware\s+developer\b",
            r"\bfull[-\s]?stack\b", r"\bfront[-\s]?end\b",
            r"\bapplication\s+engineer\b", r"\bapplication\s+developer\b",
            r"\bweb\s+developer\b", r"\bswe\b", r"\bsde\b",
        ],
    ),
]


# Explicit non-technical titles that should never be mapped to technical families via description
_NON_TECH_TITLE_PATTERN = re.compile(
    r"\b(?:sales|marketing|recruiter|recruiting|talent\s+acquisition|hr|human\s+resources|legal|compliance|"
    r"accountant|accounts\s+payable|accounts\s+receivable|payroll|receptionist|customer\s+service|cst|content\s+writer|"
    r"helpdesk|vendor\s+onboarding|onboarding|support\s+desk|customer\s+support|virtual\s+drive|recruitment\s+drive)\b"
)


def classify_role_family(title: str, description: str = "") -> str:
    """Deterministically classify a role title into its canonical RoleFamily.

    Title carries authoritative weight. Description is only checked for supporting
    signals when title is ambiguous or generic.
    """
    t_lower = (title or "").lower().replace("_", " ").replace("-", " ").strip()
    if not t_lower:
        return RoleFamily.OTHER

    # 1. Direct title regex match (highest precedence)
    for family, patterns in _ROLE_FAMILY_PATTERNS:
        for pat in patterns:
            if re.search(pat, t_lower):
                return family

    # Guard: Non-technical titles never map to engineering families via description
    if _NON_TECH_TITLE_PATTERN.search(t_lower):
        return RoleFamily.OTHER

    # 2. If title is generic (e.g. "Engineer", "Developer", "Consultant", "Specialist")
    # or not matched, check description for explicit role family markers.
    d_lower = (description or "")[:1000].lower()
    for family, patterns in _ROLE_FAMILY_PATTERNS:
        if family == RoleFamily.SAP_ERP:
            # Description must explicitly indicate an SAP engineering/consulting role, not casual tool mention
            if re.search(r"\b(?:abap|s/4hana|sap\s+(?:consultant|developer|engineer|specialist|lead|architect|functional|technical|basis|fico|hana|implementation))\b", d_lower):
                return family
            continue
        for pat in patterns:
            if re.search(pat, d_lower):
                return family

    return RoleFamily.OTHER


def evaluate_role_compatibility(
    candidate_role: str,
    job_title: str,
    job_description: str = "",
) -> tuple[str, float]:
    """Evaluate role-family compatibility between candidate desired role and a job.

    Returns (compatibility_label, compatibility_multiplier):
      - ("STRONG", 1.0): Same family or exact title anchor match.
      - ("COMPATIBLE", 0.7): Closely related cross-family (e.g. Backend <-> Full Stack SWE).
      - ("MISMATCH", 0.05): Incompatible family (e.g. SAP vs SWE, DE vs generic SWE).
    """
    cand_lower = (candidate_role or "").lower().replace("_", " ").replace("-", " ").strip()
    job_t_lower = (job_title or "").lower().replace("_", " ").replace("-", " ").strip()

    if not cand_lower:
        return "COMPATIBLE", 0.7

    # Exact or near-exact substring match always strong (e.g. "data analyst" in "Junior Data Analyst")
    if cand_lower in job_t_lower or job_t_lower in cand_lower:
        return "STRONG", 1.0

    cand_family = classify_role_family(cand_lower)
    job_family = classify_role_family(job_t_lower, job_description)

    # Both belong to the exact same role family
    if cand_family == job_family and cand_family != RoleFamily.OTHER:
        return "STRONG", 1.0

    # Defined permissible cross-family bridges:
    # 1. Backend Engineer can be compatible with generic Software Engineering (multiplier 0.7)
    if cand_family == RoleFamily.BACKEND and job_family == RoleFamily.SOFTWARE_ENGINEERING:
        if re.search(r"\bfront[-\s]?end\b", job_t_lower):
            return "MISMATCH", 0.05
        return "COMPATIBLE", 0.7

    # 2. Software Engineering candidate can consider Backend
    if cand_family == RoleFamily.SOFTWARE_ENGINEERING and job_family == RoleFamily.BACKEND:
        return "COMPATIBLE", 0.7

    # 3. Data Engineering candidate vs generic Software Engineering:
    # A generic "Software Engineer" title without Data Engineering keywords is a MISMATCH
    if cand_family == RoleFamily.DATA_ENGINEERING:
        if job_family == RoleFamily.SOFTWARE_ENGINEERING:
            if re.search(r"\bdata\b", job_t_lower):
                return "COMPATIBLE", 0.7
            return "MISMATCH", 0.05

    # 4. AI/ML candidate vs generic Software Engineering:
    # A generic "Software Engineer" title without AI/ML keywords is a MISMATCH
    if cand_family == RoleFamily.AI_ML:
        if job_family == RoleFamily.SOFTWARE_ENGINEERING:
            if re.search(r"\b(?:ai|ml|learning|data)\b", job_t_lower):
                return "COMPATIBLE", 0.7
            return "MISMATCH", 0.05

    # 5. SAP / ERP candidate vs ANYTHING other than SAP:
    if cand_family == RoleFamily.SAP_ERP and job_family != RoleFamily.SAP_ERP:
        return "MISMATCH", 0.05

    if job_family == RoleFamily.SAP_ERP and cand_family != RoleFamily.SAP_ERP:
        return "MISMATCH", 0.05

    # 6. Analytics/BI candidate vs Software Engineering / Backend:
    if cand_family == RoleFamily.ANALYTICS_BI and job_family in (
        RoleFamily.SOFTWARE_ENGINEERING,
        RoleFamily.BACKEND,
        RoleFamily.DEVOPS_CLOUD,
    ):
        return "MISMATCH", 0.05

    if job_family == RoleFamily.ANALYTICS_BI and cand_family in (
        RoleFamily.SOFTWARE_ENGINEERING,
        RoleFamily.BACKEND,
    ):
        return "MISMATCH", 0.05

    # Default fallback when families differ
    return "MISMATCH", 0.05
