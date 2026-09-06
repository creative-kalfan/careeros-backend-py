"""Job Description Parser for CareerOS ATS Intelligence (Step 4)."""

from __future__ import annotations

import re
from typing import List, Dict, Optional, Tuple, Any
from datetime import datetime
import logging

from app.models.ats import (
    ParsedJobDescription,
    ParsedJobRequirement,
    JobRequirementType,
    SkillNormalizationEntry,
    SkillNormalizationDictionary
)

logger = logging.getLogger(__name__)

# Requirement lexicon (V2). Each concept is a meaningful, multi-word where possible,
# job-relevant requirement. The analyzer only evaluates concepts that are actually
# present in the JD (relevance filter), so generic JD prose can never become a
# "missing keyword". Categories map to JobRequirementType; importance drives scoring.
REQUIREMENT_LEXICON: List[Dict[str, Any]] = [
    # --- Core IT Service Desk / Ticketing skills ---
    {"canonical": "ServiceNow", "category": "skill", "importance": "high",
     "variants": ["ServiceNow", "Service Now"]},
    {"canonical": "BMC Remedy", "category": "skill", "importance": "high",
     "variants": ["BMC Remedy", "Remedy", "BMC"]},
    {"canonical": "ITSM", "category": "skill", "importance": "high",
     "variants": ["ITSM", "IT Service Management", "IT service management"]},
    {"canonical": "Incident Management", "category": "skill", "importance": "high",
     "variants": ["Incident Management", "Incident management", "incident ticket handling"]},
    {"canonical": "Service Level Agreements (SLA)", "category": "skill", "importance": "medium",
     "variants": ["Service Level Agreement", "Service Level Agreements", "SLA", "SLAs"]},
    {"canonical": "Ticketing Systems", "category": "skill", "importance": "medium",
     "variants": ["Ticketing Systems", "Ticketing System", "ticketing tool", "ticketing tools"]},
    {"canonical": "Ticket Lifecycle", "category": "skill", "importance": "medium",
     "variants": ["ticket lifecycle", "ticket life cycle", "ticket management"]},
    {"canonical": "Knowledge Base", "category": "skill", "importance": "medium",
     "variants": ["Knowledge Base", "Knowledge Bases", "knowledge management", "Knowledge Management"]},
    # --- Process / Governance / Compliance ---
    {"canonical": "SOP Adherence", "category": "skill", "importance": "medium",
     "variants": ["SOP", "SOPs", "SOP adherence", "standard operating procedure", "standard operating procedures", "SOP guidelines"]},
    {"canonical": "Process Compliance & Governance", "category": "skill", "importance": "medium",
     "variants": ["process compliance", "process governance", "compliance & governance", "compliance and governance",
                  "process compliance & governance", "governance and compliance", "regulatory compliance", "process compliance and governance"]},
    {"canonical": "Audit Trail & Documentation", "category": "skill", "importance": "medium",
     "variants": ["audit trail", "audit documentation", "process documentation", "documentation",
                  "audit trail & documentation", "audit trail and documentation", "operational documentation"]},
    {"canonical": "Process Discipline", "category": "skill", "importance": "medium",
     "variants": ["process discipline", "operational discipline", "procedural discipline", "procedural rigor"]},

    # --- Cross-Functional Collaboration ---
    {"canonical": "Cross-Functional Collaboration", "category": "skill", "importance": "medium",
     "variants": ["cross-functional collaboration", "cross functional collaboration", "cross-functional",
                  "cross functional", "collaborating across teams", "cross-functional coordination"]},
    {"canonical": "Stakeholder Coordination", "category": "skill", "importance": "medium",
     "variants": ["stakeholder coordination", "stakeholder management", "stakeholder communication",
                  "coordinating with stakeholders", "stakeholder engagement"]},

    # --- Reporting & Quality ---
    {"canonical": "Operational Reporting & Metrics", "category": "skill", "importance": "medium",
     "variants": ["operational reporting", "operational metrics", "reporting & metrics", "reporting and metrics",
                  "operational reporting & metrics", "operational reports", "kpi reporting", "performance metrics"]},
    {"canonical": "Data Verification & Accuracy", "category": "skill", "importance": "medium",
     "variants": ["data verification", "data accuracy", "verification & accuracy", "verification and accuracy",
                  "data verification & accuracy", "data validation", "data integrity"]},
    {"canonical": "Attention to Detail & Quality Validation", "category": "skill", "importance": "medium",
     "variants": ["attention to detail", "quality validation", "quality verification", "quality check",
                  "attention to detail & quality validation", "quality assurance"]},

    # --- Business / Finance ---
    {"canonical": "SAP ERP", "category": "skill", "importance": "high",
     "variants": ["SAP", "SAP ERP", "SAP ECC", "SAP S/4HANA", "SAP system", "SAP financial"]},
    {"canonical": "Microsoft Excel / Spreadsheets", "category": "skill", "importance": "high",
     "variants": ["Excel", "Microsoft Excel", "MS Excel", "spreadsheets", "advanced Excel", "vlookup", "pivot tables"]},
    {"canonical": "Billing & Invoicing", "category": "skill", "importance": "high",
     "variants": ["billing", "invoicing", "billing & invoicing", "billing and invoicing",
                  "client billing", "customer billing", "invoice processing"]},
    {"canonical": "Contract-to-Cash / Order Management", "category": "skill", "importance": "high",
     "variants": ["contract-to-cash", "order management", "order-to-cash", "contract to cash",
                  "order to cash", "O2C", "C2C"]},
    {"canonical": "Account Reconciliation", "category": "skill", "importance": "high",
     "variants": ["account reconciliation", "reconciliation", "account reconciliations",
                  "reconciling accounts", "balance sheet reconciliation", "bank reconciliation"]},
    {"canonical": "Revenue Recognition (ASC 606 / IFRS 15)", "category": "skill", "importance": "high",
     "variants": ["revenue recognition", "ASC 606", "IFRS 15", "ASC606", "IFRS15", "rev rec"]},

    # --- Software / Data Engineering skills (carried over from the legacy skill dictionary) ---
    {"canonical": "Python", "category": "skill", "importance": "high",
     "variants": ["Python", "Python programming", "Python development"]},
    {"canonical": "SQL", "category": "skill", "importance": "high",
     "variants": ["SQL", "SQL Server", "Structured Query Language"]},
    {"canonical": "PostgreSQL", "category": "skill", "importance": "medium",
     "variants": ["PostgreSQL", "Postgres", "PostgresSQL"]},
    {"canonical": "Power BI", "category": "skill", "importance": "medium",
     "variants": ["Power BI", "Microsoft Power BI", "PowerBI"]},
    {"canonical": "Tableau", "category": "skill", "importance": "low",
     "variants": ["Tableau", "Tableau Software", "Tableau Desktop"]},
    {"canonical": "JavaScript", "category": "skill", "importance": "medium",
     "variants": ["JavaScript", "JS", "ECMAScript"]},
    {"canonical": "TypeScript", "category": "skill", "importance": "medium",
     "variants": ["TypeScript", "TS", "Typed JavaScript"]},
    {"canonical": "React", "category": "skill", "importance": "medium",
     "variants": ["React", "React.js", "ReactJS"]},
    {"canonical": "Node.js", "category": "skill", "importance": "medium",
     "variants": ["Node.js", "Node", "NodeJS"]},
    {"canonical": "Docker", "category": "skill", "importance": "medium",
     "variants": ["Docker", "Docker Container", "Docker Engine"]},
    {"canonical": "JIRA", "category": "skill", "importance": "medium",
     "variants": ["JIRA", "jira", "Atlassian JIRA"]},
    {"canonical": "Confluence", "category": "skill", "importance": "medium",
     "variants": ["Confluence", "confluence", "Atlassian Confluence"]},

    # --- Directory / Identity / Productivity ---
    {"canonical": "Active Directory", "category": "skill", "importance": "high",
     "variants": ["Active Directory", "AD ", "AD (", "Active directory"]},
    {"canonical": "Microsoft 365 / O365", "category": "skill", "importance": "high",
     "variants": ["Microsoft 365", "MS 365", "M365", "Office 365", "O365", "MS Office 365", "M365 (Office 365)"]},
    {"canonical": "MS Office Suite", "category": "skill", "importance": "medium",
     "variants": ["MS Office", "Microsoft Office", "Office Suite", "MS office suite"]},
    {"canonical": "PowerShell", "category": "skill", "importance": "medium",
     "variants": ["PowerShell", "Powershell"]},

    # --- Support delivery channels / modes ---
    {"canonical": "L1 Technical Support", "category": "requirement", "importance": "high",
     "variants": ["L1", "L1 Support", "Level 1", "Level 1 Technical Support", "L1 Technical Support", "L1 Technical"]},
    {"canonical": "Service Desk Management", "category": "requirement", "importance": "high",
     "variants": ["Service Desk", "IT Service Desk", "Service Desk Management", "service desk management"]},
    {"canonical": "Remote User Support", "category": "requirement", "importance": "medium",
     "variants": ["remote user support", "remote support", "remote desktop support", "Remote Desktop"]},
    {"canonical": "Voice-based Support", "category": "requirement", "importance": "medium",
     "variants": ["voice-based support", "voice-based technical support", "voice support", "voice-based"]},
    {"canonical": "Email / Chat Support", "category": "requirement", "importance": "medium",
     "variants": ["email support", "chat support", "email/chat", "Email/chat/remote desktop support"]},
    {"canonical": "Desktop Support", "category": "requirement", "importance": "medium",
     "variants": ["Desktop Support", "desktop support", "Desktop"]},
    {"canonical": "Hardware/Software Troubleshooting", "category": "skill", "importance": "medium",
     "variants": ["Hardware troubleshooting", "Software troubleshooting", "hardware/software troubleshooting",
                  "troubleshooting", "Troubleshooting"]},
    {"canonical": "24x7 Support", "category": "work_condition", "importance": "low",
     "variants": ["24x7", "24/7", "24x7 support", "round-the-clock", "round the clock"]},

    # --- Soft / cross-functional skills ---
    {"canonical": "Customer Service", "category": "skill", "importance": "high",
     "variants": ["Customer Service", "Customer Support", "customer service", "customer support"]},
    {"canonical": "Verbal & Written Communication", "category": "skill", "importance": "high",
     "variants": ["Verbal communication", "Written communication", "communication skills",
                  "verbal and written", "written and verbal"]},
    {"canonical": "Email Etiquette", "category": "skill", "importance": "low",
     "variants": ["Email etiquette", "email etiquette"]},
    {"canonical": "Problem Solving", "category": "skill", "importance": "high",
     "variants": ["Problem solving", "Problem-solving", "problem-solving", "analytical skills",
                  "Analytical skills", "problem solving"]},

    # --- Qualifications ---
    {"canonical": "Bachelor's Degree", "category": "qualification", "importance": "medium",
     "variants": ["Bachelor", "Bachelor's degree", "Bachelors degree", "B.Tech", "B.S", "B.E",
                  "Bachelor of", "degree in"]},
    {"canonical": "Full-time Education (15 years)", "category": "qualification", "importance": "low",
     "variants": ["15 years of full-time education", "15 years of education", "full-time education"]},
    {"canonical": "Computer Science / IT Field", "category": "qualification", "importance": "medium",
     "variants": ["Computer Science", "computer science", "information technology", "IT field"]},

    # --- Experience ---
    {"canonical": "0-2 Years Experience", "category": "experience", "importance": "low",
     "variants": ["0-2 years", "0–2 years", "0 - 2 years", "fresher", "0 to 2 years"]},
    {"canonical": "IT Support Experience", "category": "experience", "importance": "medium",
     "variants": ["IT support experience", "technical support experience", "service desk experience"]},

    # --- Work conditions (Accenture Service Desk specifics) ---
    {"canonical": "Rotational Shifts", "category": "work_condition", "importance": "medium",
     "variants": ["rotational shifts", "rotational shift", "9.5-hour rotational shifts",
                  "9.5 hour shifts", "9.5-hour"]},
    {"canonical": "US / Night Shifts", "category": "work_condition", "importance": "low",
     "variants": ["US shift", "US/night shifts", "night shift", "night shifts", "US shifts"]},
    {"canonical": "Weekends / Public Holidays", "category": "work_condition", "importance": "low",
     "variants": ["weekends", "public holidays", "public holiday"]},
    {"canonical": "Bengaluru Location", "category": "work_condition", "importance": "low",
     "variants": ["Bengaluru", "Bangalore"]},

    # --- Experience requirements ---
    {"canonical": "3-5 Years Experience", "category": "experience", "importance": "medium",
     "variants": ["3-5 years", "3–5 years", "3 to 5 years", "mid-level"]},
    {"canonical": "5+ Years Experience", "category": "experience", "importance": "medium",
     "variants": ["5+ years", "5 plus years", "more than 5 years", "experienced"]},
    {"canonical": "10+ Years Experience", "category": "experience", "importance": "high",
     "variants": ["10+ years", "10 plus years", "more than 10 years", "senior-level"]},

    # --- Location requirements ---
    {"canonical": "Pune Location", "category": "work_condition", "importance": "low",
     "variants": ["Pune"]},
    {"canonical": "Hybrid Work", "category": "work_condition", "importance": "medium",
     "variants": ["hybrid", "hybrid work", "remote hybrid", "flexible location"]},
    {"canonical": "Remote Work", "category": "work_condition", "importance": "medium",
     "variants": ["remote", "work from home", "work-from-home", "remote work"]},

    # --- Communication/language requirements ---
    {"canonical": "English Proficiency", "category": "skill", "importance": "medium",
     "variants": ["English", "English proficiency", "proficiency in English", "fluent English"]},
    {"canonical": "Local Language", "category": "skill", "importance": "low",
     "variants": ["local language", "regional language", "language proficiency"]},

    # --- Certification requirements ---
    {"canonical": "ITIL Foundation", "category": "qualification", "importance": "medium",
     "variants": ["ITIL", "ITIL Foundation", "itil foundation"]},
    {"canonical": "COBIT", "category": "qualification", "importance": "low",
     "variants": ["COBIT", "cobit"]},
]

# Words/phrases that must NOT create partial-match evidence on their own (too generic).
# These are common JD prose words that are NOT job requirements.
_PARTIAL_STOP_WORDS = {
    # Generic adjectives/prose that should never be keywords
    "excellent", "typical", "primary", "office", "users", "provide", "ensuring",
    "high-quality", "vital", "day", "work", "role", "position", "company",
    "team", "candidate", "successful", "dynamic", "proactive", "detail-oriented",
    "self-motivated", "creative", "flexible", "competitive",
    # Common filler words
    "and", "or", "but", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "should",
    "could", "may", "might", "must", "can", "this", "that", "these", "those",
    # Words that are often JD noise when standalone
    "experience", "skills", "knowledge", "ability", "capacity", "aptitude",
    "understanding", "familiar", "exposure", "expert", "expertise",
    # Ambiguous strength words that should not be standalone requirements
    "mandatory", "must", "required", "essential", "nicely", "highly",
    # Very common verbs/actions that are not requirements per se
    "manage", "lead", "develop", "design", "create", "build", "implement",
    "maintain", "support", "operate", "handle", "process", "manage",
}


class JobDescriptionParser:
    """Parses job descriptions into structured data for ATS analysis."""

    def __init__(self):
        self.skill_dictionary = self._load_default_skill_dictionary()

    def _load_default_skill_dictionary(self) -> SkillNormalizationDictionary:
        """Load default skill normalization dictionary."""
        return SkillNormalizationDictionary(
            entries=[
                SkillNormalizationEntry(
                    canonical_name="PostgreSQL",
                    variants=["Postgres", "PostgreSQL", "PostgresSQL"],
                    category="database"
                ),
                SkillNormalizationEntry(
                    canonical_name="Python",
                    variants=["Python", "Python programming", "Python development"],
                    category="programming"
                ),
                SkillNormalizationEntry(
                    canonical_name="SQL",
                    variants=["SQL", "SQL Server", "Structured Query Language"],
                    category="database"
                ),
                SkillNormalizationEntry(
                    canonical_name="Power BI",
                    variants=["Power BI", "Microsoft Power BI", "PowerBI"],
                    category="analytics"
                ),
                SkillNormalizationEntry(
                    canonical_name="Tableau",
                    variants=["Tableau", "Tableau Software", "Tableau Desktop"],
                    category="analytics"
                ),
                SkillNormalizationEntry(
                    canonical_name="JavaScript",
                    variants=["JavaScript", "JS", "ECMAScript"],
                    category="programming"
                ),
                SkillNormalizationEntry(
                    canonical_name="TypeScript",
                    variants=["TypeScript", "TS", "Typed JavaScript"],
                    category="programming"
                ),
                SkillNormalizationEntry(
                    canonical_name="React",
                    variants=["React", "React.js", "ReactJS"],
                    category="framework"
                ),
                SkillNormalizationEntry(
                    canonical_name="Node.js",
                    variants=["Node.js", "Node", "NodeJS"],
                    category="framework"
                ),
                SkillNormalizationEntry(
                    canonical_name="Docker",
                    variants=["Docker", "Docker Container", "Docker Engine"],
                    category="devops"
                ),
            ],
            version="1.0"
        )

    def normalize_skill(self, skill: str) -> str:
        """Normalize skill names using the skill dictionary."""
        skill_lower = skill.lower().strip()

        # Check for exact matches first
        for entry in self.skill_dictionary.entries:
            if skill_lower in [v.lower() for v in entry.variants]:
                return entry.canonical_name

        # Check for partial matches (e.g., "Postgres" in "PostgreSQL")
        for entry in self.skill_dictionary.entries:
            for variant in entry.variants:
                if variant.lower() in skill_lower or skill_lower in variant.lower():
                    return entry.canonical_name

        return skill

    def _variant_in_text(self, text_lower: str, variant: str) -> bool:
        """Check whether a JD concept variant is present in the JD text.

        Single tokens use word boundaries so short variants like 'AD' or 'SLA'
        do not false-match inside larger words ('administrator', 'slack').
        Multi-word phrases / phrases with punctuation use substring matching.
        """
        v = variant.lower().strip()
        if not v:
            return False
        if " " in v or "-" in v or "/" in v or not v.isalnum():
            return v in text_lower
        return re.search(rf"\b{re.escape(v)}\b", text_lower) is not None

    def extract_job_concepts(self, job_description: str) -> List[Dict[str, Any]]:
        """Extract only job-relevant requirement concepts that actually appear in the JD.

        Returns a list of concept dicts (canonical, category, importance, variants,
        job_evidence) for lexicon concepts whose variants are found in the JD text.
        Generic JD prose never produces a concept, so it can never become a 'missing'.
        """
        jd_lower = (job_description or "").lower()
        concepts = []
        # The lexicon may legitimately contain the same canonical concept more
        # than once (e.g. listed under two sections). Emit each canonical
        # concept at most once so downstream requirement lists (and React keys
        # derived from the canonical name) stay unique.
        seen_canonicals = set()
        for concept in REQUIREMENT_LEXICON:
            if concept["canonical"] in seen_canonicals:
                continue
            job_evidence = None
            for variant in concept["variants"]:
                if self._variant_in_text(jd_lower, variant):
                    job_evidence = variant
                    break
            if job_evidence is not None:
                seen_canonicals.add(concept["canonical"])
                concepts.append({
                    "canonical": concept["canonical"],
                    "category": concept["category"],
                    "importance": concept["importance"],
                    "variants": concept["variants"],
                    "job_evidence": job_evidence,
                })
        return concepts

    def _extract_section_content(self, text: str, section_headers: List[str]) -> Dict[str, str]:
        """Extract content from different sections of a job description."""
        sections = {}
        text_lower = text.lower()
        matched_spans: List[Tuple[int, int]] = []

        for header in section_headers:
            header_clean = header.rstrip(":")
            # Try to find section headers in various formats
            patterns = [
                rf"{re.escape(header)}:",
                rf"{re.escape(header)}\s*[:—-]",
                rf"^{re.escape(header)}$",
                rf"[\n\r]+\s*{re.escape(header)}\s*[\n\r]+"
            ]
            if header != header_clean:
                patterns.insert(0, rf"^{re.escape(header)}")
                patterns.insert(1, rf"[\n\r]+\s*{re.escape(header)}")

            for pattern in patterns:
                matches = list(re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE))
                if matches:
                    start_pos = matches[0].end()
                    # Skip if this section header position was already extracted by an equivalent header
                    if any(abs(span[0] - start_pos) <= len(header) + 2 for span in matched_spans):
                        break

                    # Find next section header or end of text
                    next_header_pos = len(text)
                    for other_header in section_headers:
                        if other_header.lower().rstrip(":") == header.lower().rstrip(":"):
                            continue
                        other_matches = list(re.finditer(
                            rf"{re.escape(other_header)}:|{re.escape(other_header)}\s*[:—-]|[\n\r]+\s*{re.escape(other_header)}",
                            text, re.IGNORECASE | re.MULTILINE
                        ))
                        if other_matches:
                            for match in other_matches:
                                if match.start() > start_pos and match.start() < next_header_pos:
                                    next_header_pos = match.start()

                    section_content = text[start_pos:next_header_pos].strip()
                    sections[header] = section_content
                    matched_spans.append((start_pos, next_header_pos))
                    break

        return sections

    def _extract_keywords(self, text: str) -> List[str]:
        """Extract keywords from text using basic NLP techniques."""
        # Remove common stop words and punctuation
        stop_words = {
            'the', 'and', 'or', 'of', 'to', 'in', 'a', 'an', 'for', 'with', 'on', 'at', 'by',
            'is', 'are', 'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had', 'do', 'does',
            'did', 'will', 'would', 'should', 'could', 'may', 'might', 'must', 'can', 'this', 'that',
            'these', 'those', 'i', 'you', 'he', 'she', 'it', 'we', 'they', 'my', 'your', 'his', 'her',
            'its', 'our', 'their', 'me', 'him', 'us', 'them', 'as', 'from', 'into', 'through', 'during',
            'before', 'after', 'above', 'below', 'up', 'down', 'out', 'off', 'over', 'under', 'again',
            'further', 'then', 'once', 'here', 'there', 'when', 'where', 'why', 'how', 'all', 'any',
            'both', 'each', 'few', 'more', 'most', 'other', 'some', 'such', 'no', 'nor', 'not', 'only',
            'own', 'same', 'so', 'than', 'too', 'very', 's', 't', 'can', 'just', 'don', 'should', 'now',
            'we', 'are', 'looking', 'senior', 'developer', 'experience', 'building', 'degree', 'field',
            'responsibilities', 'requirements'
        }

        # Extract words (allow all alphanumeric words, but filter out common ones)
        words = re.findall(r'\b[a-zA-Z0-9_\-\.\+#]+', text)
        keywords = []
        for word in words:
            word_lower = word.lower().strip(".")
            if len(word_lower) >= 2 and word_lower not in stop_words and not word_lower.isdigit():
                keywords.append(word_lower)

        return list(set(keywords))  # Remove duplicates

    def _extract_skills(self, text: str) -> List[str]:
        """Extract skills from text using pattern matching and normalization."""
        # Scan text for any variants in our skill dictionary
        skills = set()
        text_lower = text.lower()
        
        for entry in self.skill_dictionary.entries:
            for variant in entry.variants:
                pattern = rf"\b{re.escape(variant.lower())}\b"
                if re.search(pattern, text_lower):
                    skills.add(entry.canonical_name)
                    
        return list(skills)

    def _extract_requirements_from_text(self, text: str, default_type: JobRequirementType) -> List[ParsedJobRequirement]:
        """Extract bullet points and classify them."""
        requirements = []
        lines = text.split("\n")
        
        for line in lines:
            line = line.strip()
            # Clean up bullet characters
            if line.startswith(("•", "·", "-", "*", "1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9.", "0.")):
                clean_text = re.sub(r"^[\s•·\-*\d\.\)]+", "", line).strip()
                if clean_text:
                    requirements.append(ParsedJobRequirement(
                        text=clean_text,
                        requirement_type=default_type,
                        confidence=0.9
                    ))
            elif len(line) > 20 and (line.endswith(".") or line.endswith(";")):
                # Check if it looks like a sentence requirement
                requirements.append(ParsedJobRequirement(
                    text=line,
                    requirement_type=default_type,
                    confidence=0.7
                ))
        return requirements

    def _extract_years_of_experience(self, text: str) -> Optional[str]:
        """Extract years of experience requirements."""
        patterns = [
            r'(\d+)\s*(?:-|to)\s*(\d+)\s*years?',
            r'(\d+)\s*[\+-]?\s*years?',
            r'(\d+)\s*years?'
        ]

        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                if len(matches[0]) == 2:  # Range
                    return f"{matches[0][0]}-{matches[0][1]} years"
                else:  # Single number
                    return f"{matches[0][0]} years"

        return None

    def parse_job_description(self, job_description: str, job_title: Optional[str] = None, company: Optional[str] = None) -> ParsedJobDescription:
        """Main method to parse a job description."""
        if not job_description or not job_description.strip():
            raise ValueError("Job description cannot be empty")

        # Define headers to scan
        headers_config = {
            "Requirements": JobRequirementType.REQUIRED,
            "Qualifications": JobRequirementType.QUALIFICATION,
            "Skills": JobRequirementType.SKILL,
            "Responsibilities": JobRequirementType.RESPONSIBILITY,
            "Education": JobRequirementType.QUALIFICATION,
            "Experience": JobRequirementType.REQUIRED,
            "Certifications": JobRequirementType.QUALIFICATION,
            "Key Responsibilities": JobRequirementType.RESPONSIBILITY,
            "Technical Skills": JobRequirementType.SKILL,
            "Preferred Qualifications": JobRequirementType.PREFERRED,
            "What you'll do": JobRequirementType.RESPONSIBILITY,
            "What you will do": JobRequirementType.RESPONSIBILITY,
            "What You'll Do:": JobRequirementType.RESPONSIBILITY,
            "What You'll Do": JobRequirementType.RESPONSIBILITY,
            "What you'll bring": JobRequirementType.QUALIFICATION,
            "What you bring": JobRequirementType.QUALIFICATION,
            "What You'll Bring:": JobRequirementType.QUALIFICATION,
            "What You'll Bring": JobRequirementType.QUALIFICATION,
            "What we're looking for": JobRequirementType.QUALIFICATION,
            "Who you are": JobRequirementType.QUALIFICATION,
            "Role responsibilities": JobRequirementType.RESPONSIBILITY,
            "Key duties": JobRequirementType.RESPONSIBILITY,
            "Basic qualifications": JobRequirementType.QUALIFICATION,
            "Minimum qualifications": JobRequirementType.QUALIFICATION,
            "Preferred qualifications": JobRequirementType.PREFERRED,
            "Nice to have": JobRequirementType.PREFERRED,
        }

        sections = self._extract_section_content(job_description, list(headers_config.keys()))

        all_requirements = []
        for header, section_text in sections.items():
            req_type = headers_config[header]
            all_requirements.extend(self._extract_requirements_from_text(section_text, req_type))

        # If no sections were parsed, fallback to parsing the entire text as general requirements
        if not all_requirements:
            lines = job_description.split("\n")
            for line in lines:
                line = line.strip()
                if line.startswith(("•", "·", "-", "*")):
                    clean_text = re.sub(r"^[\s•·\-*]+", "", line).strip()
                    if clean_text:
                        all_requirements.append(ParsedJobRequirement(
                            text=clean_text,
                            requirement_type=JobRequirementType.KEYWORD,
                            confidence=0.5
                        ))

        # Separate requirements into their list containers
        required_skills = []
        preferred_skills = []
        technical_skills = []
        soft_skills = []
        responsibilities = []
        qualifications = []
        education_requirements = []
        certifications = []
        tools_technologies = []

        all_skills = self._extract_skills(job_description)

        for req in all_requirements:
            if req.requirement_type == JobRequirementType.RESPONSIBILITY:
                responsibilities.append(req.text)
            elif req.requirement_type in (JobRequirementType.REQUIRED, JobRequirementType.QUALIFICATION):
                if any(word in req.text.lower() for word in ['degree', 'education', 'bachelor', 'master', 'study', 'phd', 'diploma', 'bs', 'ms', 'b.s.', 'm.s.']):
                    education_requirements.append(req.text)
                elif any(word in req.text.lower() for word in ['certification', 'certified']):
                    certifications.append(req.text)
                elif req.requirement_type == JobRequirementType.REQUIRED:
                    required_skills.append(req.text)
                else:
                    qualifications.append(req.text)

        # Extract keywords — meaningful, JD-relevant requirement concepts only
        # (replaces naive whole-document tokenization that produced hundreds of
        # low-value lexical 'missing' tokens).
        concepts = self.extract_job_concepts(job_description)
        all_keywords = [c["canonical"] for c in concepts]
        tools_technologies = [c["canonical"] for c in concepts if c["category"] == "skill"]

        # Extract years of experience
        years_of_experience = self._extract_years_of_experience(job_description)

        return ParsedJobDescription(
            raw_text=job_description,
            job_title=job_title,
            company=company,
            required_skills=required_skills,
            preferred_skills=preferred_skills,
            technical_skills=technical_skills,
            soft_skills=soft_skills,
            years_of_experience=years_of_experience,
            education_requirements=education_requirements,
            certifications=certifications,
            responsibilities=responsibilities,
            qualifications=qualifications,
            keywords=all_keywords,
            tools_technologies=tools_technologies,
            parsed_requirements=all_requirements,
            extracted_at=datetime.now()
        )
