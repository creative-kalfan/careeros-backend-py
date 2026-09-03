"""Shared deterministic extraction utilities for job descriptions.

These utilities are used by both ATS analysis and Job Intelligence to
ensure consistent interpretation of the same job description text.
"""

from __future__ import annotations

import re
from typing import Any

from app.models.ats import (
    JobRequirementType,
    ParsedJobRequirement,
    SkillNormalizationDictionary,
    SkillNormalizationEntry,
)


# ---------------------------------------------------------------------------
# HTML stripping
# ---------------------------------------------------------------------------

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_HTML_ENTITY_RE = re.compile(r"&[a-zA-Z0-9#]+;")


def strip_html(text: str) -> str:
    """Remove HTML tags and decode common entities, preserving newlines."""
    # Preserve list item markers first.
    text = re.sub(r"<li[^>]*>", "\n• ", text)
    # Add newlines around heading and structural tags.
    text = re.sub(r"</?(h[1-6]|ul|ol|table|tr|td|th|thead|tbody|section|article|header|footer|main|nav|aside|blockquote|pre|code|br)[^>]*>", "\n", text, flags=re.IGNORECASE)
    # Remove remaining tags (including p, div, span, strong, em, etc.) with spaces.
    text = _HTML_TAG_RE.sub(" ", text)
    text = _HTML_ENTITY_RE.sub(" ", text)
    # Collapse multiple spaces on the same line, but keep newlines.
    lines = text.split("\n")
    lines = [" ".join(line.split()) for line in lines]
    return "\n".join(lines).strip()


# ---------------------------------------------------------------------------
# Skill normalization
# ---------------------------------------------------------------------------

_SKILL_ALIASES: dict[str, str] = {
    "postgres": "postgresql",
    "postgresql": "postgresql",
    "postgres sql": "postgresql",
    "power bi": "power bi",
    "microsoft power bi": "power bi",
    "powerbi": "power bi",
    "python3": "python",
    "python 3": "python",
    "js": "javascript",
    "javascript": "javascript",
    "ts": "typescript",
    "typescript": "typescript",
    "react.js": "react",
    "reactjs": "react",
    "node.js": "node.js",
    "nodejs": "node.js",
    "docker": "docker",
    "docker container": "docker",
    "kubernetes": "kubernetes",
    "k8s": "kubernetes",
    "aws": "aws",
    "amazon web services": "aws",
    "gcp": "google cloud",
    "google cloud": "google cloud",
    "azure": "azure",
    "microsoft azure": "azure",
    "sql server": "sql server",
    "structured query language": "sql",
    "tableau": "tableau",
    "tableau desktop": "tableau",
    "machine learning": "machine learning",
    "ml": "machine learning",
    "ai": "artificial intelligence",
    "artificial intelligence": "artificial intelligence",
    "nlp": "natural language processing",
    "natural language processing": "natural language processing",
    "ci/cd": "ci/cd",
    "continuous integration": "ci/cd",
    "continuous deployment": "ci/cd",
    "git": "git",
    "github": "github",
    "gitlab": "gitlab",
    "jira": "jira",
    "confluence": "confluence",
    "rest api": "rest api",
    "rest": "rest api",
    "graphql": "graphql",
    "api": "api",
    "microservices": "microservices",
    "microservice": "microservices",
    "agile": "agile",
    "scrum": "scrum",
    "kanban": "kanban",
    "project management": "project management",
    "pmp": "pmp",
    "cfa": "cfa",
    "cpa": "cpa",
    "aws certified": "aws certified",
    "azure certified": "azure certified",
    "google certified": "google certified",
}

_SKILL_CATEGORIES: dict[str, str] = {
    "postgresql": "database",
    "sql": "database",
    "mysql": "database",
    "mongodb": "database",
    "redis": "database",
    "power bi": "analytics",
    "tableau": "analytics",
    "python": "programming",
    "javascript": "programming",
    "typescript": "programming",
    "react": "framework",
    "node.js": "framework",
    "docker": "devops",
    "kubernetes": "devops",
    "aws": "cloud",
    "azure": "cloud",
    "google cloud": "cloud",
    "machine learning": "ai",
    "artificial intelligence": "ai",
    "natural language processing": "ai",
    "git": "tools",
    "github": "tools",
    "jira": "tools",
}


def normalize_skill_name(skill: str) -> str:
    """Normalize a skill name to its canonical form."""
    skill_lower = skill.lower().strip()
    return _SKILL_ALIASES.get(skill_lower, skill.strip())


def get_skill_category(skill: str) -> str | None:
    """Return the category for a normalized skill name."""
    canonical = normalize_skill_name(skill)
    return _SKILL_CATEGORIES.get(canonical.lower())


def build_skill_dictionary() -> SkillNormalizationDictionary:
    """Build a skill normalization dictionary from the static aliases."""
    entries: list[SkillNormalizationEntry] = {}
    for alias, canonical in _SKILL_ALIASES.items():
        canonical_entry = entries.get(canonical)
        if canonical_entry is None:
            entries[canonical] = SkillNormalizationEntry(
                canonical_name=canonical,
                variants=[canonical],
                category=_SKILL_CATEGORIES.get(canonical.lower()),
            )
        else:
            if alias not in canonical_entry.variants:
                canonical_entry.variants.append(alias)

    return SkillNormalizationDictionary(
        entries=list(entries.values()),
        version="1.0",
    )


# ---------------------------------------------------------------------------
# Section extraction
# ---------------------------------------------------------------------------

_SECTION_HEADERS = [
    "Responsibilities",
    "What you'll do",
    "Role responsibilities",
    "Key duties",
    "You will",
    "Requirements",
    "Qualifications",
    "What we're looking for",
    "Basic qualifications",
    "Preferred qualifications",
    "Skills",
    "Technical Skills",
    "Experience",
    "Education",
    "Certifications",
]


def extract_section_content(text: str, headers: list[str] | None = None) -> dict[str, str]:
    """Extract content blocks following known section headers."""
    headers = headers or _SECTION_HEADERS
    sections: dict[str, str] = {}
    text_lower = text.lower()

    for header in headers:
        header_lower = header.lower()
        pattern = re.compile(
            rf"(?:^|[\n\r]+)\s*{re.escape(header)}\s*(?:[:—-]|[\n\r])",
            re.IGNORECASE,
        )
        match = pattern.search(text)
        if not match:
            continue
        start = match.end()
        end = len(text)
        for other in headers:
            if other.lower() == header_lower:
                continue
            other_pattern = re.compile(
                rf"(?:^|[\n\r]+)\s*{re.escape(other)}\s*(?:[:—-]|[\n\r])",
                re.IGNORECASE,
            )
            other_match = other_pattern.search(text, pos=start)
            if other_match and other_match.start() < end:
                end = other_match.start()
        sections[header] = text[start:end].strip()

    return sections


# ---------------------------------------------------------------------------
# Experience extraction
# ---------------------------------------------------------------------------

_EXPERIENCE_PATTERNS = [
    re.compile(r"(\d+)\s*[-–to]\s*(\d+)\s*years?", re.IGNORECASE),
    re.compile(r"(\d+)\s*[\+-]?\s*years?", re.IGNORECASE),
    re.compile(r"(\d+)\s*years?", re.IGNORECASE),
]


def extract_years_of_experience(text: str) -> tuple[float | None, float | None]:
    """Return (years_min, years_max) extracted from text, or (None, None)."""
    for pattern in _EXPERIENCE_PATTERNS:
        match = pattern.search(text)
        if match:
            groups = match.groups()
            if len(groups) == 2:
                try:
                    return float(groups[0]), float(groups[1])
                except ValueError:
                    continue
            try:
                value = float(groups[0])
                return value, None
            except ValueError:
                continue
    return None, None


_SENIORITY_INDICATORS: dict[str, tuple[str, float]] = {
    "entry level": ("entry", 0.9),
    "entry-level": ("entry", 0.9),
    "junior": ("junior", 0.85),
    "associate": ("junior", 0.7),
    "mid level": ("mid", 0.85),
    "mid-level": ("mid", 0.85),
    "intermediate": ("mid", 0.7),
    "senior": ("senior", 0.9),
    "lead": ("lead", 0.85),
    "staff": ("staff", 0.8),
    "principal": ("principal", 0.85),
    "manager": ("manager", 0.8),
    "director": ("director", 0.85),
    "vp": ("executive", 0.85),
    "vice president": ("executive", 0.9),
    "c-level": ("executive", 0.9),
    "graduate": ("entry", 0.8),
    "intern": ("intern", 0.9),
}


def classify_seniority(text: str, title: str | None = None) -> tuple[str | None, str]:
    """Classify seniority from text/title. Returns (level, confidence)."""
    haystack = " ".join(filter(None, [text.lower(), (title or "").lower()]))
    best_level: str | None = None
    best_confidence = "low"
    best_score = 0.0

    for indicator, (level, score) in _SENIORITY_INDICATORS.items():
        if indicator in haystack:
            if score > best_score:
                best_score = score
                best_level = level
                best_confidence = "high" if score >= 0.85 else "medium"

    return best_level, best_confidence


# ---------------------------------------------------------------------------
# Education extraction
# ---------------------------------------------------------------------------

_EDUCATION_PATTERNS = [
    (r"bachelor['']?s?\s+(?:degree|of science|of arts|in)", "bachelor"),
    (r"b\.?s\.?", "bachelor"),
    (r"b\.?a\.?", "bachelor"),
    (r"master['']?s?\s+(?:degree|of science|of arts|in)", "master"),
    (r"m\.?s\.?", "master"),
    (r"m\.?b\.?a\.?", "mba"),
    (r"mba", "mba"),
    (r"ph\.?d\.?", "phd"),
    (r"doctorate", "phd"),
    (r"diploma", "diploma"),
    (r"engineering\s+degree", "engineering"),
    (r"computer\s+science", "computer science"),
    (r"information\s+technology", "information technology"),
    (r"business\s+administration", "business administration"),
    (r"finance", "finance"),
    (r"analytics", "analytics"),
]


def extract_education(text: str) -> list[dict[str, Any]]:
    """Extract education requirements from text."""
    found: list[dict[str, Any]] = []
    text_lower = text.lower()
    for pattern, label in _EDUCATION_PATTERNS:
        if re.search(pattern, text_lower):
            required = any(word in text_lower for word in ["required", "must have", "minimum"])
            found.append({
                "degree": label,
                "field": None,
                "required": required,
                "confidence": "medium",
            })
    # Deduplicate by degree
    seen = set()
    deduped = []
    for item in found:
        key = item["degree"]
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped


# ---------------------------------------------------------------------------
# Certification extraction
# ---------------------------------------------------------------------------

_CERTIFICATION_PATTERNS = [
    r"aws\s+certified",
    r"azure\s+certified",
    r"google\s+certified",
    r"pmp",
    r"cfa",
    r"cpa",
    r"cissp",
    r"comptia",
    r"security\+",
    r"network\+",
    r"cisa",
    r"cism",
    r"itil",
    r"scrum\s+master",
    r"csdm",
]


def extract_certifications(text: str) -> list[dict[str, Any]]:
    """Extract certification requirements from text."""
    found = []
    text_lower = text.lower()
    for pattern in _CERTIFICATION_PATTERNS:
        match = re.search(pattern, text_lower)
        if match:
            required = any(
                word in text_lower
                for word in ["required", "must have", "certification required", "certified"]
            )
            found.append({
                "name": match.group(0),
                "required": required,
                "confidence": "medium",
            })
    # Deduplicate
    seen = set()
    deduped = []
    for item in found:
        key = item["name"].lower()
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped


# ---------------------------------------------------------------------------
# Responsibility / requirement extraction
# ---------------------------------------------------------------------------

_RESPONSIBILITY_HEADERS = [
    "Responsibilities",
    "What you'll do",
    "What You'll Achieve",
    "Role responsibilities",
    "Key duties",
    "You will",
    "Key responsibilities",
    "Duties",
]


_REQUIREMENT_HEADERS = [
    "Requirements",
    "Qualifications",
    "What we're looking for",
    "Basic qualifications",
    "Preferred qualifications",
    "Skills You'll Need To Bring",
    "What You'll Need To Bring",
    "Skills",
    "Technical Skills",
    "Nice to Haves",
    "Nice to have",
]


def _clean_bullet(line: str) -> str:
    return re.sub(r"^[\s•·\-*\d\.\)]+", "", line).strip()


def extract_bullet_points(text: str) -> list[str]:
    """Extract bullet points from text."""
    bullets = []
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith(("•", "·", "-", "*", "1.", "2.", "3.", "4.", "5.")):
            cleaned = _clean_bullet(line)
            if cleaned and len(cleaned) > 3:
                bullets.append(cleaned)
    return bullets


def extract_responsibilities(text: str) -> list[str]:
    """Extract responsibility statements from text."""
    sections = extract_section_content(text, _RESPONSIBILITY_HEADERS)
    responsibilities = []
    for section_text in sections.values():
        responsibilities.extend(extract_bullet_points(section_text))
    return responsibilities


def extract_requirements(text: str) -> list[dict[str, Any]]:
    """Extract requirements from text."""
    sections = extract_section_content(text, _REQUIREMENT_HEADERS)
    requirements = []
    for header, section_text in sections.items():
        req_type = (
            JobRequirementType.PREFERRED.value
            if "preferred" in header.lower()
            else JobRequirementType.REQUIRED.value
        )
        for bullet in extract_bullet_points(section_text):
            requirements.append({
                "text": bullet,
                "type": req_type,
                "importance": "high" if req_type == "required" else "medium",
                "confidence": "medium",
            })
    return requirements


# ---------------------------------------------------------------------------
# Keyword extraction
# ---------------------------------------------------------------------------

_STOP_WORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are", "aren't", "as", "at",
    "be", "because", "been", "before", "being", "below", "between", "both", "but", "by",
    "can", "can't", "cannot", "could", "couldn't",
    "did", "didn't", "do", "does", "doesn't", "doing", "don't", "down", "during",
    "each",
    "few", "for", "from", "further",
    "get", "got", "had", "hadn't", "has", "hasn't", "have", "haven't", "having", "he", "he'd", "he'll", "he's", "her", "here", "here's", "hers", "herself", "him", "himself", "his", "how", "how's",
    "i", "i'd", "i'll", "i'm", "i've", "if", "in", "into", "is", "isn't", "it", "it's", "its", "itself",
    "let", "like", "ll", "me", "more", "most", "mustn't", "my", "myself",
    "no", "nor", "not", "now",
    "of", "off", "on", "once", "only", "or", "other", "our", "ours", "ourselves", "out", "over", "own",
    "re", "s", "same", "shan't", "she", "she'd", "she'll", "she's", "should", "shouldn't", "so", "some", "such",
    "t", "than", "that", "that's", "the", "their", "theirs", "them", "themselves", "then", "there", "there's", "these", "they", "they'd", "they'll", "they're", "they've", "this", "those", "through", "to", "too",
    "under", "until", "up",
    "ve", "very",
    "was", "wasn't", "we", "we'd", "we'll", "we're", "we've", "were", "weren't", "what", "what's", "when", "when's", "where", "where's", "which", "while", "who", "who's", "whom", "why", "why's", "with", "won't", "would", "wouldn't",
    "you", "you'd", "you'll", "you're", "you've", "your", "yours", "yourself", "yourselves",
    # Additional common words and section headers
    "the", "and", "or", "of", "to", "in", "a", "an", "for", "with", "on", "at", "by",
    "is", "are", "was", "were", "be", "been", "being", "have", "has", "had", "do", "does",
    "did", "will", "would", "should", "could", "may", "might", "must", "can", "this", "that",
    "these", "those", "i", "you", "he", "she", "it", "we", "they", "my", "your", "his", "her",
    "its", "our", "their", "me", "him", "us", "them", "as", "from", "into", "through", "during",
    "before", "after", "above", "below", "up", "down", "out", "off", "over", "under", "again",
    "further", "then", "once", "here", "there", "when", "where", "why", "how", "all", "any",
    "both", "each", "few", "more", "most", "other", "some", "such", "no", "nor", "not", "only",
    "own", "same", "so", "than", "too", "very", "s", "t", "can", "just", "don", "should", "now",
    "we", "are", "looking", "senior", "developer", "experience", "building", "degree", "field",
    "responsibilities", "requirements", "preferred", "qualifications", "skills", "education",
    "certification", "certified", "years", "year", "plus", "minimum", "maximum", "ideal",
    "able", "about", "across", "after", "against", "ago", "ahead", "along", "among", "around",
    "away", "back", "because", "before", "behind", "between", "beyond", "come", "could", "day",
    "days", "did", "done", "down", "each", "either", "else", "end", "even", "every", "few",
    "first", "for", "from", "get", "gets", "getting", "give", "go", "goes", "going", "gone", "got",
    "had", "has", "have", "he", "her", "here", "hers", "herself", "him", "himself", "his", "how",
    "however", "if", "into", "its", "itself", "just", "keep", "last", "later", "least", "left",
    "less", "let", "like", "likely", "may", "might", "more", "most", "much", "must", "my", "myself",
    "near", "next", "nor", "not", "now", "off", "often", "once", "only", "other", "our", "ours",
    "out", "over", "own", "part", "past", "per", "put", "quite", "rather", "really", "said", "say",
    "says", "see", "seem", "seen", "self", "set", "shall", "she", "should", "show", "since", "so",
    "some", "something", "such", "take", "than", "that", "the", "their", "theirs", "them",
    "themselves", "then", "there", "these", "they", "this", "those", "through", "throughout",
    "thu", "till", "to", "together", "too", "toward", "towards", "under", "until", "up", "us",
    "use", "used", "uses", "very", "want", "was", "way", "we", "well", "were", "what", "whatever",
    "when", "whenever", "where", "whereas", "wherever", "whether", "which", "while", "who",
    "whom", "whose", "why", "will", "with", "within", "without", "would", "yet", "you", "your",
    "yours", "yourself", "yourselves",
}


def extract_keywords(text: str) -> list[str]:
    """Extract meaningful keywords from text."""
    words = re.findall(r"\b[a-zA-Z0-9_\-\.\+#]+\b", text)
    keywords = []
    for word in words:
        word_lower = word.lower()
        if (
            len(word_lower) >= 3
            and word_lower not in _STOP_WORDS
            and not word_lower.isdigit()
            and "#" not in word_lower
        ):
            keywords.append(word_lower)
    return list(set(keywords))


# ---------------------------------------------------------------------------
# Work arrangement
# ---------------------------------------------------------------------------

_WORK_ARRANGEMENT_PATTERNS = [
    (r"\bremote\b", "remote", 0.9),
    (r"\bhybrid\b", "hybrid", 0.9),
    (r"\bon[- ]?site\b", "onsite", 0.9),
    (r"\bin[- ]?office\b", "onsite", 0.85),
    (r"\bwork\s+from\s+office\b", "onsite", 0.85),
    (r"\bwork\s+from\s+home\b", "remote", 0.85),
    (r"\bwfh\b", "remote", 0.8),
    (r"\bflexible\s+location\b", "hybrid", 0.7),
]


def classify_work_arrangement(text: str) -> tuple[str, str]:
    """Classify work arrangement from text. Returns (type, confidence)."""
    text_lower = text.lower()
    for pattern, arrangement, confidence in _WORK_ARRANGEMENT_PATTERNS:
        if re.search(pattern, text_lower):
            return arrangement, "high" if confidence >= 0.85 else "medium"
    return "unknown", "low"
