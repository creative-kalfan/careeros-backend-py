"""Universal JD requirement extraction for CareerOS tailoring.

Resume-agnostic replacement for lexicon-only JD analysis. Works for ANY
candidate, role, industry, or experience level: it derives requirements from
the structure and language of the job description itself instead of matching
against a hard-coded concept list.

Pipeline position (see universal_tailoring_engine.py)::

    JD text -> UniversalJD -> evidence matching -> tailoring

Categories covered (Part 1 of the product spec):
hard / preferred / responsibilities / technical skills / domain knowledge /
tools / education / experience / soft skills / behavioral signals /
certifications / location / work authorization / role terminology.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Generic, domain-independent signal patterns (NOT resume/role specific).
# These describe how JDs are written in any industry, not what any
# particular JD says.
# ---------------------------------------------------------------------------

_EDUCATION_PATTERNS = (
    r"bachelor|master(?:'s)?\b|mba\b|ph\.?d\b|doctorate|associate(?:'s)? degree|"
    r"diploma|b\.?tech\b|m\.?tech\b|b\.?s\.?\b|m\.?s\.?\b|b\.?e\.?\b|degree in|"
    r"field of study|years of (?:full-time )?education"
)

_CERT_PATTERNS = (
    r"certif(?:ied|ication)|license[d]?\b|itil\b|cobit\b|pmp\b|cpa\b|cfa\b|"
    r"aws certified|azure certified|credential"
)

_YEARS_PATTERNS = r"\d+\s*(?:-|to|–|\+)?\s*\d*\s*\+?\s*years?"

_LOCATION_PATTERNS = (
    r"location|based in|on-site|onsite|remote|hybrid|relocat|"
    r"bengaluru|bangalore|pune|mumbai|delhi|hyderabad|chennai|kolkata|"
    r"work from home|work-from-home"
)

_WORK_AUTH_PATTERNS = (
    r"work authorization|authorized to work|visa|sponsorship|citizen|"
    r"security clearance|eligible to work"
)

_SHIFT_PATTERNS = (
    r"shift|rotational|night shift|weekend|public holiday|24x7|24/7|round-the-clock"
)

_APPLICATION_INSTRUCTION_PATTERNS = (
    r"complete (?:your|the) application|submit (?:your|the) (?:application|resume|cv)|"
    r"equal opportunity|eeo employer|affirmative action|accommodations? (?:available|upon request)|"
    r"background check|drug (?:screen|test)|apply online|click (?:here to )?apply|"
    r"must be legally authorized|will not sponsor|privacy policy|terms of (?:use|service)|"
    r"how to apply|application process|recruitment process"
)

_SECTION_HEADER_ALIASES: Dict[str, str] = {
    "requirements": "hard",
    "basic qualifications": "hard",
    "minimum qualifications": "hard",
    "must have": "hard",
    "required": "hard",
    "what you'll bring": "hard",
    "what you bring": "hard",
    "what we're looking for": "hard",
    "who you are": "hard",
    "preferred qualifications": "preferred",
    "preferred": "preferred",
    "nice to have": "preferred",
    "bonus": "preferred",
    "plus": "preferred",
    "responsibilities": "responsibility",
    "what you'll do": "responsibility",
    "what you will do": "responsibility",
    "role responsibilities": "responsibility",
    "key duties": "responsibility",
    "key responsibilities": "responsibility",
    "skills": "skill",
    "technical skills": "skill",
    "education": "education",
    "experience": "experience",
    "certifications": "certification",
}

_HARD_SIGNALS = ("must", "required", "requirement", "mandatory", "essential")
_PREFERRED_SIGNALS = ("preferred", "nice to have", "bonus", "plus", "desired")

# Generic English verbs that must never become single-word skill requirements
# on their own (they are sentence-initial prose in any industry's JD, not
# concrete skills or tools).
_GENERIC_LEADING_VERBS = frozenset(
    {
        "maintain", "execute", "perform", "prepare", "drive", "ensure",
        "handle", "manage", "lead", "develop", "design", "create", "build",
        "implement", "maintained", "executed", "performed", "prepared",
        "support", "provide", "deliver", "coordinate", "conduct", "analyze",
        "demonstrate", "possess", "strong", "proven", "excellent", "bachelor",
    }
)

# Generic filler that must never become a requirement on its own.
_STOP_PHRASES = frozenset(
    {
        "and", "or", "the", "a", "an", "we", "are", "looking", "for", "with",
        "will", "you", "your", "our", "team", "role", "position", "company",
        "candidate", "successful", "dynamic", "excellent", "primary", "typical",
        "experience", "experiences", "experienced", "skill", "skills",
        "skilled", "year", "years", "strong", "proven", "ability",
        "abilities", "proficiency", "proficient", "knowledge",
        "seeking", "responsible", "qualification", "including", "such",
        "etc", "eg", "ie",
    }
)

# Morphological families that suffix-stripping alone cannot unify
# ("analysis"/"analyze"/"analytical" share no suffix-stripped stem, yet are
# the same requirement concept). Generic English morphology, not
# role-specific vocabulary.
_CANONICAL_STEMS = {
    "analysis": "analy",
    "analyses": "analy",
    "analyze": "analy",
    "analyzed": "analy",
    "analyzing": "analy",
    "analytical": "analy",
    "analytics": "analy",
    "dataset": "data",
    "datasets": "data",
}

_CAPITALIZED_PHRASE_RE = re.compile(r"\b[A-Z][A-Za-z0-9+_./#-]{1,}(?:\s+[A-Z][A-Za-z0-9+_./#-]{1,}){0,3}")
_LIST_INTRO_RE = re.compile(
    r"(?:proficienc(?:y|t) in|experience (?:with|in)|knowledge of|hands-?on (?:experience )?"
    r"(?:with|in)|familiarity with|exposure to|including|such as|like)\s*:?\s*(.+)",
    re.IGNORECASE,
)
_BULLET_RE = re.compile(r"^\s*(?:[•·▪▶●○-]\s+|\*\s+|\d+[.)]\s+)")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class UniversalRequirement:
    """A single JD-derived requirement with provenance."""

    text: str
    normalized_key: str
    category: str  # hard|preferred|responsibility|technical_skill|domain_knowledge|
    # tool|education|experience|soft_skill|behavioral|certification|
    # location|work_authorization|terminology
    importance: str = "medium"  # high|medium|low
    source_section: str = "general"
    jd_evidence: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "normalized_key": self.normalized_key,
            "category": self.category,
            "importance": self.importance,
            "source_section": self.source_section,
            "jd_evidence": self.jd_evidence,
        }


@dataclass
class UniversalJD:
    """Structured, resume-agnostic view of a job description."""

    raw_text: str = ""
    job_title: Optional[str] = None
    company: Optional[str] = None
    requirements: List[UniversalRequirement] = field(default_factory=list)

    # Convenience views -------------------------------------------------
    @property
    def hard(self) -> List[UniversalRequirement]:
        return [r for r in self.requirements if r.category == "hard"]

    @property
    def preferred(self) -> List[UniversalRequirement]:
        return [r for r in self.requirements if r.category == "preferred"]

    @property
    def responsibilities(self) -> List[UniversalRequirement]:
        return [r for r in self.requirements if r.category == "responsibility"]

    @property
    def technical_skills(self) -> List[str]:
        return [r.text for r in self.requirements if r.category in ("technical_skill", "tool")]

    @property
    def all_phrases(self) -> List[str]:
        return [r.text for r in self.requirements]


# ---------------------------------------------------------------------------
# Normalization — semantic equivalence without a fixed vocabulary
# ---------------------------------------------------------------------------

def _stem(token: str) -> str:
    """Cheap domain-independent stemmer (suffix stripping only)."""
    t = token.lower()
    if t in _CANONICAL_STEMS:
        return _CANONICAL_STEMS[t]
    for suffix in ("ization", "isation", "ing", "tion", "sion", "ment", "ness", "ies", "es", "ed", "ly", "al", "ic", "s"):
        if len(t) - len(suffix) >= 4 and t.endswith(suffix):
            if suffix == "ies":
                return t[:-3] + "y"
            stemmed = t[: -len(suffix)]
            return _CANONICAL_STEMS.get(stemmed, stemmed)
    return t


def normalize_key(phrase: str) -> str:
    """Canonical key: lowercased stem-sorted substantive tokens."""
    tokens = re.findall(r"[a-z0-9+#./-]+", (phrase or "").lower())
    stems = sorted({_stem(t) for t in tokens if len(t) > 2 and t not in _STOP_PHRASES})
    return " ".join(stems)


def are_equivalent(a: str, b: str, threshold: float = 0.5) -> bool:
    """True when two phrases are semantically equivalent requirements.

    Uses stem-set Jaccard similarity so "data analysis", "analyze datasets"
    and "analytical skills" group together when they share the analytic stem,
    while unrelated phrases ("payroll" vs "python") stay distinct.
    """
    ka, kb = set(normalize_key(a).split()), set(normalize_key(b).split())
    if not ka or not kb:
        return False
    if ka == kb:
        return True
    inter = ka & kb
    if not inter:
        return False
    union = ka | kb
    return len(inter) / len(union) >= threshold


def group_equivalent_requirements(
    phrases: List[str], threshold: float = 0.5
) -> List[List[str]]:
    """Cluster phrases into semantically-equivalent groups."""
    groups: List[List[str]] = []
    for phrase in phrases:
        placed = False
        for group in groups:
            if any(are_equivalent(phrase, member, threshold) for member in group):
                group.append(phrase)
                placed = True
                break
        if not placed:
            groups.append([phrase])
    return groups


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def _split_sections(jd_text: str) -> List[tuple[str, str]]:
    """Split JD into (section_kind, section_text) using generic headers."""
    text = jd_text or ""
    # Find header lines like "Requirements:", "What You'll Do", "Must have -"
    header_re = re.compile(
        r"(?im)^\s*(requirements|qualifications|skills|responsibilities|education|"
        r"experience|certifications|key responsibilities|technical skills|"
        r"preferred qualifications|nice to have|basic qualifications|"
        r"minimum qualifications|what you.ll (?:do|bring)|what you will do|"
        r"what we.re looking for|who you are|role responsibilities|key duties|"
        r"must have|bonus|plus)\s*[:—\-–]?\s*$"
    )
    matches = list(header_re.finditer(text))
    if not matches:
        return [("general", text)]
    sections: List[tuple[str, str]] = []
    # Leading prose before the first header is still informative.
    if matches[0].start() > 0:
        sections.append(("general", text[: matches[0].start()]))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        raw_header = m.group(1).strip().lower().rstrip(":")
        kind = _SECTION_HEADER_ALIASES.get(raw_header, "general")
        sections.append((kind, text[m.end(): end]))
    return sections


def _split_statements(section_text: str) -> List[str]:
    """Split a section into candidate requirement statements."""
    statements: List[str] = []
    for line in (section_text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        if _BULLET_RE.match(line):
            cleaned = _BULLET_RE.sub("", line).strip()
            if len(cleaned) >= 3:
                statements.append(cleaned)
        elif len(line) > 25 and line[-1] in ".;:":
            statements.append(line.strip(" .;:"))
    if not statements and (section_text or "").strip():
        # Unstructured paragraph JD: split into sentences.
        for sent in re.split(r"(?<=[.!?;])\s+", section_text.strip()):
            sent = sent.strip(" •·-")
            if len(sent) >= 12:
                statements.append(sent)
    return statements


def _classify_statement(statement: str, section_kind: str) -> tuple[str, str]:
    """Return (category, importance) using domain-independent cues."""
    low = statement.lower()
    if re.search(_APPLICATION_INSTRUCTION_PATTERNS, low):
        return "boilerplate", "low"
    if re.search(_EDUCATION_PATTERNS, low):
        return "education", "medium"
    if re.search(_CERT_PATTERNS, low):
        return "certification", "medium"
    if re.search(_YEARS_PATTERNS, low) and any(
        w in low for w in ("year", "experience", "fresher", "senior", "junior", "mid")
    ):
        return "experience", "medium"
    if re.search(_WORK_AUTH_PATTERNS, low):
        return "work_authorization", "medium"
    if re.search(_LOCATION_PATTERNS, low) or re.search(_SHIFT_PATTERNS, low):
        return "location", "low"
    if section_kind == "hard":
        return "hard", "high"
    if section_kind == "preferred":
        return "preferred", "low"
    if section_kind == "responsibility":
        return "responsibility", "medium"
    if section_kind == "education":
        return "education", "medium"
    if section_kind == "certification":
        return "certification", "medium"
    if section_kind == "experience":
        return "experience", "medium"
    if any(s in low for s in _HARD_SIGNALS):
        return "hard", "high"
    if any(s in low for s in _PREFERRED_SIGNALS):
        return "preferred", "low"
    # Default: treat as role terminology / domain knowledge at medium weight.
    lowered_kind = section_kind if section_kind != "general" else "terminology"
    if lowered_kind == "skill":
        return "technical_skill", "medium"
    return lowered_kind if lowered_kind in (
        "technical_skill", "domain_knowledge", "tool", "soft_skill",
        "behavioral", "terminology",
    ) else "terminology", "medium"


def _extract_skill_phrases(statement: str) -> List[str]:
    """Pull concrete skill/tool phrases out of a statement, generically."""
    phrases: List[str] = []
    # 1. Explicit list introductions: "proficiency in X, Y and Z".
    m = _LIST_INTRO_RE.search(statement)
    if m:
        tail = m.group(1)
        for chunk in re.split(r"[,;/|]|\s+and\s+|\s+or\s+", tail):
            chunk = chunk.strip(" .;:()[]\"'")
            if 1 < len(chunk) <= 48 and chunk.lower() not in _STOP_PHRASES:
                if chunk.lower() in _GENERIC_LEADING_VERBS:
                    continue
                # Keep only the leading noun chunk (drop trailing verbs).
                chunk = re.split(r"\s+(?:to|for|with|in|on|of|at)\s+", chunk)[0].strip()
                if len(chunk) > 1:
                    phrases.append(chunk)
    # 2. Capitalized technology/product phrases (any industry).
    for cap in _CAPITALIZED_PHRASE_RE.findall(statement):
        cap = cap.strip(" .;:()")
        if 1 < len(cap) <= 48 and cap.lower() not in _STOP_PHRASES:
            # Single generic verbs ("Maintain ...", "Drive ...") are sentence
            # prose, not skills — drop them so they can never be "matched".
            if " " not in cap and cap.lower() in _GENERIC_LEADING_VERBS:
                continue
            if cap not in phrases:
                phrases.append(cap)
    return phrases[:8]


def _refine_category(statement: str, category: str) -> str:
    """Distinguish tools / soft skills / behavioral signals generically."""
    low = statement.lower()
    tool_cues = ("tool", "software", "platform", "system", "erp", "proficiency in",
                 "hands-on", "hands on")
    soft_cues = ("communication", "collaboration", "team", "stakeholder",
                 "attention to detail", "problem solv", "customer service",
                 "interpersonal", "leadership", "adaptab", "time management")
    behavioral_cues = ("ownership", "bias for action", "discipline", "compliance",
                       "governance", "adherence", "work ethic", "accountab")
    if category in ("hard", "preferred", "technical_skill", "terminology"):
        if any(c in low for c in tool_cues) or re.search(
            r"\b[A-Z][A-Za-z0-9+_./#-]{1,}\b", statement
        ):
            # Keep hard/preferred as-is (they carry importance); only refine
            # generic terminology into tool/skill buckets.
            if category == "terminology":
                return "tool" if any(c in low for c in tool_cues) else "technical_skill"
        if category == "terminology" and any(c in low for c in soft_cues):
            return "soft_skill"
        if category == "terminology" and any(c in low for c in behavioral_cues):
            return "behavioral"
    return category


def parse_universal_jd(
    job_description: str,
    job_title: Optional[str] = None,
    company: Optional[str] = None,
) -> UniversalJD:
    """Parse ANY job description into normalized universal requirements."""
    if not job_description or not job_description.strip():
        raise ValueError("Job description cannot be empty")
    universal = UniversalJD(
        raw_text=job_description, job_title=job_title, company=company
    )
    seen_keys: set[str] = set()
    for section_kind, section_text in _split_sections(job_description):
        for statement in _split_statements(section_text):
            category, importance = _classify_statement(statement, section_kind)
            category = _refine_category(statement, category)
            key = normalize_key(statement)
            if not key or key in seen_keys:
                continue
            seen_keys.add(key)
            universal.requirements.append(
                UniversalRequirement(
                    text=statement[:280],
                    normalized_key=key,
                    category=category,
                    importance=importance,
                    source_section=section_kind,
                    jd_evidence=statement[:280],
                )
            )
            # Also index concrete skill phrases as their own requirements so
            # tailoring can align on tools without a fixed vocabulary.
            for phrase in _extract_skill_phrases(statement):
                pkey = normalize_key(phrase)
                if not pkey or pkey in seen_keys:
                    continue
                seen_keys.add(pkey)
                pcat = _refine_category(phrase, "technical_skill")
                universal.requirements.append(
                    UniversalRequirement(
                        text=phrase,
                        normalized_key=pkey,
                        category=pcat,
                        importance=importance,
                        source_section=section_kind,
                        jd_evidence=statement[:280],
                    )
                )
    # Role title itself is terminology the resume may legitimately target.
    if job_title and job_title.strip():
        tkey = normalize_key(job_title)
        if tkey and tkey not in seen_keys:
            seen_keys.add(tkey)
            universal.requirements.append(
                UniversalRequirement(
                    text=job_title.strip(),
                    normalized_key=tkey,
                    category="terminology",
                    importance="medium",
                    source_section="title",
                    jd_evidence=job_title.strip(),
                )
            )
    return universal
