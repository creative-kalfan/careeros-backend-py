"""Centralized CareerOS role taxonomy.

Maps role families to canonical roles and aliases. Used by:
- role normalization (user input → canonical role)
- job title classification
- related-role matching
- ingestion query generation
"""

from __future__ import annotations

from typing import Any

# Each entry: category -> list of role families.
# A role family is { "canonical": str, "aliases": [str], "related": [str] }
_ROLE_TAXONOMY: dict[str, list[dict[str, Any]]] = {
    "Software Engineering": [
        {
            "canonical": "Software Engineer",
            "aliases": [
                "software engineer", "software eng", "swe", "sde",
                "software developer", "software dev",
                "application developer", "application engineer",
                "backend software engineer", "frontend software engineer",
                "full stack engineer", "full-stack engineer",
                "senior software engineer", "staff software engineer",
                "principal software engineer", "lead software engineer",
                "software architect",
            ],
            "related": [
                "Backend Developer", "Frontend Developer", "Full Stack Developer",
                "DevOps Engineer", "Site Reliability Engineer", "Platform Engineer",
                "Solutions Architect",
            ],
        },
        {
            "canonical": "Backend Developer",
            "aliases": [
                "backend developer", "back-end developer", "backend eng",
                "back-end eng", "backend software engineer",
                "api developer", "server-side developer",
                "java developer", "python developer", "go developer",
                "golang developer", ".net developer", "c# developer",
            ],
            "related": ["Software Engineer", "Full Stack Developer", "DevOps Engineer"],
        },
        {
            "canonical": "Frontend Developer",
            "aliases": [
                "frontend developer", "front-end developer", "frontend eng",
                "front-end eng", "frontend software engineer",
                "ui developer", "web developer", "react developer",
                "javascript developer", "typescript developer",
                "angular developer", "vue developer",
            ],
            "related": ["Software Engineer", "Full Stack Developer", "UI Designer"],
        },
        {
            "canonical": "Full Stack Developer",
            "aliases": [
                "full stack developer", "full-stack developer",
                "full stack eng", "full-stack eng",
                "fullstack developer", "fullstack engineer",
            ],
            "related": ["Software Engineer", "Backend Developer", "Frontend Developer"],
        },
        {
            "canonical": "Mobile Developer",
            "aliases": [
                "mobile developer", "mobile engineer",
                "ios developer", "android developer",
                "swift developer", "kotlin developer",
                "react native developer", "flutter developer",
                "mobile application developer", "mobile app developer",
            ],
            "related": ["Software Engineer", "Frontend Developer"],
        },
        {
            "canonical": "DevOps Engineer",
            "aliases": [
                "devops engineer", "devops", "dev ops engineer",
                "site reliability engineer", "sre", "site reliability",
                "platform engineer", "infrastructure engineer",
                "release engineer", "build engineer",
                "cloud devops engineer",
            ],
            "related": [
                "Software Engineer", "Cloud Engineer", "Platform Engineer",
                "Site Reliability Engineer",
            ],
        },
        {
            "canonical": "Cloud Engineer",
            "aliases": [
                "cloud engineer", "cloud architect",
                "aws engineer", "azure engineer", "gcp engineer",
                "cloud platform engineer", "cloud infrastructure engineer",
            ],
            "related": ["DevOps Engineer", "Platform Engineer", "Solutions Architect"],
        },
        {
            "canonical": "QA Engineer",
            "aliases": [
                "qa engineer", "quality assurance engineer",
                "test engineer", "automation engineer",
                "quality engineer", "software tester",
                "sdet", "software development engineer in test",
                "qa lead", "test lead", "qa manager",
            ],
            "related": ["Software Engineer", "Automation Engineer"],
        },
        {
            "canonical": "Security Engineer",
            "aliases": [
                "security engineer", "security analyst",
                "appsec engineer", "infosec engineer",
                "cybersecurity engineer", "cyber security engineer",
                "detection and response", "threat detection",
                "security architect",
            ],
            "related": ["Network Engineer", "Systems Engineer", "DevOps Engineer"],
        },
        {
            "canonical": "Network Engineer",
            "aliases": [
                "network engineer", "network administrator",
                "network architect", "network security engineer",
            ],
            "related": ["Security Engineer", "Systems Engineer", "Cloud Engineer"],
        },
        {
            "canonical": "Systems Engineer",
            "aliases": [
                "systems engineer", "system engineer",
                "systems administrator", "sysadmin",
            ],
            "related": ["DevOps Engineer", "Network Engineer", "Cloud Engineer"],
        },
        {
            "canonical": "Solutions Architect",
            "aliases": [
                "solutions architect", "solution architect",
                "technical architect", "software architect",
                "enterprise architect", "cloud architect",
            ],
            "related": [
                "Software Engineer", "Cloud Engineer", "Platform Engineer",
                "Technical Program Manager",
            ],
        },
        {
            "canonical": "Technical Support Engineer",
            "aliases": [
                "technical support engineer", "technical support",
                "it support engineer", "it support",
                "support engineer", "help desk engineer",
                "desktop support engineer", "technical support specialist",
            ],
            "related": ["Systems Engineer", "DevOps Engineer"],
        },
        {
            "canonical": "Database Administrator",
            "aliases": [
                "database administrator", "dba",
                "database engineer", "database developer",
                "sql developer", "data engineer",
            ],
            "related": ["Data Engineer", "Backend Developer", "Cloud Engineer"],
        },
    ],
    "Data & Analytics": [
        {
            "canonical": "Data Analyst",
            "aliases": [
                "data analyst", "data analytics analyst",
                "senior data analyst", "junior data analyst",
                "data analyst ii", "data analyst iii",
                "analytics analyst", "reporting analyst",
                "business intelligence analyst", "bi analyst",
                "data insights analyst",
                "operations analyst", "marketing data analyst",
                "financial data analyst", "product data analyst",
                "data visualization analyst", "mis analyst",
                "mis executive",
            ],
            "related": [
                "Business Analyst", "BI Developer", "Product Analyst",
                "Marketing Analyst", "Financial Analyst", "Risk Analyst",
                "Operations Analyst", "Analytics Engineer", "Decision Scientist",
                "Data Scientist", "Business Intelligence Developer",
            ],
        },
        {
            "canonical": "BI Developer",
            "aliases": [
                "business intelligence developer", "bi developer",
                "power bi developer", "tableau developer",
                "looker developer", "business intelligence engineer",
            ],
            "related": [
                "Data Analyst", "Business Analyst", "Data Engineer",
                "Analytics Engineer",
            ],
        },
        {
            "canonical": "Product Analyst",
            "aliases": [
                "product analyst", "product data analyst",
                "product insights analyst",
            ],
            "related": [
                "Data Analyst", "Business Analyst", "Product Manager",
                "Data Scientist",
            ],
        },
        {
            "canonical": "Marketing Analyst",
            "aliases": [
                "marketing analyst", "marketing data analyst",
                "digital marketing analyst", "seo analyst",
                "performance marketing analyst",
            ],
            "related": [
                "Data Analyst", "Business Analyst", "Product Analyst",
                "Digital Marketing Specialist",
            ],
        },
        {
            "canonical": "Risk Analyst",
            "aliases": [
                "risk analyst", "credit risk analyst",
                "fraud analyst", "operational risk analyst",
                "market risk analyst", "compliance analyst",
            ],
            "related": [
                "Data Analyst", "Financial Analyst", "Compliance Analyst",
                "Data Scientist",
            ],
        },
        {
            "canonical": "Operations Analyst",
            "aliases": [
                "operations analyst", "operational analyst",
                "business operations analyst", "supply chain analyst",
            ],
            "related": [
                "Data Analyst", "Business Analyst", "Product Analyst",
                "Operations Manager",
            ],
        },
        {
            "canonical": "Data Scientist",
            "aliases": [
                "data scientist", "senior data scientist",
                "junior data scientist", "lead data scientist",
                "principal data scientist", "staff data scientist",
                "research scientist", "decision scientist",
                "quantitative analyst",
            ],
            "related": [
                "Data Analyst", "Machine Learning Engineer", "Analytics Engineer",
                "Data Engineer",
            ],
        },
        {
            "canonical": "Analytics Engineer",
            "aliases": [
                "analytics engineer", "data analytics engineer",
            ],
            "related": [
                "Data Engineer", "Data Analyst", "BI Developer",
                "Data Scientist",
            ],
        },
        {
            "canonical": "Data Engineer",
            "aliases": [
                "data engineer", "etl engineer",
                "data platform engineer", "data infrastructure engineer",
                "big data engineer", "data warehouse engineer",
                "data integration engineer",
            ],
            "related": [
                "Software Engineer", "Data Analyst", "Data Scientist",
                "Analytics Engineer", "Database Administrator",
            ],
        },
        {
            "canonical": "Machine Learning Engineer",
            "aliases": [
                "machine learning engineer", "ml engineer",
                "ai engineer", "mlops engineer",
                "applied scientist", "research scientist",
                "deep learning engineer",
            ],
            "related": [
                "Data Scientist", "Data Engineer", "Software Engineer",
                "AI Engineer",
            ],
        },
    ],
    "Product & Business": [
        {
            "canonical": "Product Manager",
            "aliases": [
                "product manager", "product owner", "pm",
                "associate product manager", "apm",
                "senior product manager", "group product manager",
                "product lead", "head of product",
                "director of product", "vp of product",
                "technical product manager",
            ],
            "related": [
                "Business Analyst", "Project Manager", "Program Manager",
                "Product Analyst", "UX Designer",
            ],
        },
        {
            "canonical": "Business Analyst",
            "aliases": [
                "business analyst", "ba",
                "business systems analyst",
                "it business analyst", "senior business analyst",
                "junior business analyst",
                "functional analyst", "systems analyst",
            ],
            "related": [
                "Data Analyst", "Product Manager", "Project Manager",
                "Business Intelligence Analyst", "Solutions Architect",
            ],
        },
        {
            "canonical": "Project Manager",
            "aliases": [
                "project manager",
                "senior project manager", "junior project manager",
                "project coordinator", "project lead",
                "program coordinator",
            ],
            "related": [
                "Product Manager", "Program Manager", "Business Analyst",
                "Technical Program Manager",
            ],
        },
        {
            "canonical": "Program Manager",
            "aliases": [
                "program manager", "programme manager",
                "senior program manager", "technical program manager",
                "tpm", "project program manager",
            ],
            "related": [
                "Product Manager", "Project Manager",
                "Technical Program Manager", "Business Operations",
            ],
        },
        {
            "canonical": "Business Operations",
            "aliases": [
                "business operations", "bizops",
                "business operations analyst",
                "strategy analyst", "strategy consultant",
                "management consultant", "business consultant",
                "operations consultant",
            ],
            "related": [
                "Business Analyst", "Operations Manager",
                "Product Manager", "Project Manager",
            ],
        },
        {
            "canonical": "Operations Manager",
            "aliases": [
                "operations manager", "head of operations",
                "director of operations", "vp of operations",
                "chief operating officer", "coo",
            ],
            "related": [
                "Business Operations", "Project Manager",
                "Operations Analyst",
            ],
        },
    ],
    "Finance & BFSI": [
        {
            "canonical": "Accountant",
            "aliases": [
                "accountant", "senior accountant",
                "junior accountant", "staff accountant",
                "general accountant", "accounts executive",
                "accounts manager",
            ],
            "related": [
                "Financial Analyst", "Auditor", "Accounting Analyst",
            ],
        },
        {
            "canonical": "Financial Analyst",
            "aliases": [
                "financial analyst", "finance analyst",
                "senior financial analyst", "junior financial analyst",
                "investment analyst", "equity research analyst",
                "treasury analyst", "fp&a analyst",
                "accounting analyst", "corporate finance analyst",
            ],
            "related": [
                "Data Analyst", "Accountant", "Risk Analyst",
                "Investment Analyst", "FP&A Analyst",
            ],
        },
        {
            "canonical": "Auditor",
            "aliases": [
                "auditor", "internal auditor",
                "external auditor", "senior auditor",
                "it auditor", "financial auditor",
            ],
            "related": ["Accountant", "Financial Analyst", "Compliance Analyst"],
        },
        {
            "canonical": "Compliance Analyst",
            "aliases": [
                "compliance analyst", "compliance officer",
                "compliance manager", "regulatory compliance",
                "aml analyst", "kyc analyst",
            ],
            "related": [
                "Risk Analyst", "Financial Analyst", "Auditor",
                "Legal Counsel",
            ],
        },
        {
            "canonical": "Loan Analyst",
            "aliases": [
                "loan analyst", "credit analyst",
                "credit risk analyst", "lending analyst",
            ],
            "related": ["Risk Analyst", "Financial Analyst", "Banking Operations"],
        },
        {
            "canonical": "Banking Operations",
            "aliases": [
                "banking operations", "bank operations",
                "operations executive", "operations officer",
                "transaction processing",
            ],
            "related": [
                "Financial Analyst", "Loan Analyst", "Accountant",
                "Operations Manager",
            ],
        },
    ],
    "Sales & Marketing": [
        {
            "canonical": "Sales Executive",
            "aliases": [
                "sales executive", "sales representative",
                "sales rep", "account executive",
                "account manager", "business development executive",
                "bde", "business development manager",
                "bdm", "sales development representative",
                "sdr", "business development representative",
                "bdr", "inside sales",
            ],
            "related": [
                "Account Manager", "Business Development Manager",
                "Customer Success Manager",
            ],
        },
        {
            "canonical": "Account Manager",
            "aliases": [
                "account manager", "key account manager",
                "customer success manager", "csm",
                "client success manager",
            ],
            "related": [
                "Sales Executive", "Customer Success Manager",
                "Business Development Manager",
            ],
        },
        {
            "canonical": "Marketing Executive",
            "aliases": [
                "marketing executive", "marketing manager",
                "digital marketing specialist",
                "seo specialist", "seo executive",
                "performance marketing specialist",
                "brand manager", "content marketing specialist",
                "social media specialist", "growth marketer",
                "marketing specialist",
            ],
            "related": [
                "Marketing Analyst", "Digital Marketing Specialist",
                "Content Marketing Specialist", "Product Manager",
            ],
        },
        {
            "canonical": "Digital Marketing Specialist",
            "aliases": [
                "digital marketing specialist",
                "digital marketing executive",
                "performance marketing specialist",
                "growth marketing specialist",
                "sem specialist", "ppc specialist",
            ],
            "related": [
                "Marketing Executive", "SEO Specialist",
                "Content Marketing Specialist", "Marketing Analyst",
            ],
        },
        {
            "canonical": "SEO Specialist",
            "aliases": [
                "seo specialist", "seo executive",
                "seo analyst", "search engine optimization specialist",
            ],
            "related": [
                "Digital Marketing Specialist", "Marketing Executive",
                "Content Marketing Specialist",
            ],
        },
    ],
    "HR & People": [
        {
            "canonical": "Recruiter",
            "aliases": [
                "recruiter", "talent acquisition specialist",
                "talent acquisition partner", "talent acquisition lead",
                "technical recruiter", "it recruiter",
                "senior recruiter", "recruitment specialist",
                "hiring manager",
            ],
            "related": [
                "HR Executive", "HR Business Partner",
                "Human Resources Specialist",
            ],
        },
        {
            "canonical": "HR Executive",
            "aliases": [
                "hr executive", "hr specialist",
                "human resources executive",
                "human resources specialist",
                "people operations", "people ops",
                "hr generalist", "hr coordinator",
            ],
            "related": [
                "HR Business Partner", "Recruiter",
                "Learning and Development Specialist",
            ],
        },
        {
            "canonical": "HR Business Partner",
            "aliases": [
                "hr business partner", "hrbp",
                "human resources business partner",
                "senior hr business partner",
            ],
            "related": [
                "HR Executive", "Recruiter", "Business Partner",
            ],
        },
        {
            "canonical": "Learning and Development Specialist",
            "aliases": [
                "learning and development specialist",
                "learning & development specialist",
                "l&d specialist", "training specialist",
                "training coordinator", "organizational development",
            ],
            "related": [
                "HR Executive", "People Operations",
                "Instructional Designer",
            ],
        },
    ],
    "Design & Creative": [
        {
            "canonical": "UX Designer",
            "aliases": [
                "ux designer", "user experience designer",
                "senior ux designer", "lead ux designer",
                "ux/ui designer", "product designer",
            ],
            "related": [
                "UI Designer", "Product Designer", "UX Researcher",
                "Interaction Designer",
            ],
        },
        {
            "canonical": "UI Designer",
            "aliases": [
                "ui designer", "user interface designer",
                "senior ui designer", "lead ui designer",
                "visual designer", "graphic designer",
                "interface designer",
            ],
            "related": [
                "UX Designer", "Product Designer", "Graphic Designer",
                "Creative Designer",
            ],
        },
        {
            "canonical": "UX Researcher",
            "aliases": [
                "ux researcher", "user researcher",
                "user experience researcher",
                "senior user researcher",
            ],
            "related": ["UX Designer", "Product Designer", "Product Manager"],
        },
        {
            "canonical": "Product Designer",
            "aliases": [
                "product designer", "digital product designer",
                "senior product designer", "lead product designer",
                "interaction designer", "content designer",
            ],
            "related": [
                "UX Designer", "UI Designer", "UX Researcher",
                "Product Manager",
            ],
        },
        {
            "canonical": "Graphic Designer",
            "aliases": [
                "graphic designer", "visual designer",
                "senior graphic designer", "lead graphic designer",
                "brand designer", "visual communication designer",
            ],
            "related": [
                "UI Designer", "Creative Designer", "Content Designer",
            ],
        },
        {
            "canonical": "Creative Designer",
            "aliases": [
                "creative designer", "creative director",
                "art director", "content designer",
                "multimedia designer",
            ],
            "related": [
                "Graphic Designer", "UI Designer", "UX Designer",
            ],
        },
    ],
    "Customer & Operations": [
        {
            "canonical": "Customer Support",
            "aliases": [
                "customer support", "customer service representative",
                "csr", "customer support representative",
                "customer care executive", "customer care representative",
                "help desk", "support specialist",
            ],
            "related": [
                "Customer Success Manager", "Technical Support Engineer",
                "Customer Experience Specialist",
            ],
        },
        {
            "canonical": "Customer Experience Specialist",
            "aliases": [
                "customer experience specialist",
                "cx specialist", "customer experience manager",
                "customer success specialist",
            ],
            "related": [
                "Customer Support", "Customer Success Manager",
                "Operations Manager",
            ],
        },
        {
            "canonical": "Quality Analyst",
            "aliases": [
                "quality analyst", "qa analyst",
                "quality assurance analyst",
                "process quality analyst",
            ],
            "related": [
                "QA Engineer", "Operations Analyst",
                "Business Analyst",
            ],
        },
        {
            "canonical": "Workforce Management Analyst",
            "aliases": [
                "workforce management analyst",
                "wfm analyst", "workforce analyst",
                "resource management analyst",
            ],
            "related": [
                "Operations Analyst", "Business Analyst",
                "Project Manager",
            ],
        },
        {
            "canonical": "Process Associate",
            "aliases": [
                "process associate", "process executive",
                "operations executive", "operations associate",
                "back office associate", "back office executive",
                "data entry associate",
            ],
            "related": [
                "Operations Analyst", "Customer Support",
                "Business Operations",
            ],
        },
    ],
    "Supply Chain & Logistics": [
        {
            "canonical": "Supply Chain Analyst",
            "aliases": [
                "supply chain analyst",
                "supply chain specialist",
                "supply chain coordinator",
            ],
            "related": [
                "Logistics Analyst", "Procurement Analyst",
                "Operations Analyst",
            ],
        },
        {
            "canonical": "Supply Chain Manager",
            "aliases": [
                "supply chain manager",
                "head of supply chain",
                "director of supply chain",
                "supply chain lead",
            ],
            "related": [
                "Operations Manager", "Logistics Coordinator",
                "Procurement Specialist",
            ],
        },
        {
            "canonical": "Procurement Analyst",
            "aliases": [
                "procurement analyst",
                "procurement specialist",
                "purchasing analyst",
                "sourcing analyst",
            ],
            "related": [
                "Supply Chain Analyst", "Operations Analyst",
                "Supply Chain Manager",
            ],
        },
        {
            "canonical": "Logistics Coordinator",
            "aliases": [
                "logistics coordinator",
                "logistics specialist",
                "shipping coordinator",
                "transportation coordinator",
                "warehouse coordinator",
            ],
            "related": [
                "Supply Chain Analyst", "Logistics Analyst",
                "Inventory Analyst",
            ],
        },
        {
            "canonical": "Inventory Analyst",
            "aliases": [
                "inventory analyst",
                "inventory control analyst",
                "inventory manager",
                "stock controller",
            ],
            "related": [
                "Supply Chain Analyst", "Operations Analyst",
                "Logistics Coordinator",
            ],
        },
        {
            "canonical": "Demand Planner",
            "aliases": [
                "demand planner",
                "demand planning analyst",
                "forecasting analyst",
                "supply planner",
            ],
            "related": [
                "Supply Chain Analyst", "Operations Analyst",
                "Inventory Analyst",
            ],
        },
    ],
    "Engineering (Core)": [
        {
            "canonical": "Civil Engineer",
            "aliases": [
                "civil engineer", "structural engineer",
                "construction engineer", "site engineer",
                "project engineer", "senior civil engineer",
                "junior civil engineer",
            ],
            "related": [
                "Structural Engineer", "Project Engineer",
                "Site Engineer", "Quality Engineer",
            ],
        },
        {
            "canonical": "Mechanical Engineer",
            "aliases": [
                "mechanical engineer", "mechanical design engineer",
                "senior mechanical engineer",
                "junior mechanical engineer",
            ],
            "related": [
                "Manufacturing Engineer", "Industrial Engineer",
                "Quality Engineer", "Project Engineer",
            ],
        },
        {
            "canonical": "Electrical Engineer",
            "aliases": [
                "electrical engineer", "electrical design engineer",
                "senior electrical engineer",
                "junior electrical engineer",
            ],
            "related": [
                "Electronics Engineer", "Systems Engineer",
                "Manufacturing Engineer",
            ],
        },
        {
            "canonical": "Electronics Engineer",
            "aliases": [
                "electronics engineer",
                "electronics design engineer",
                "embedded engineer", "embedded systems engineer",
                "vlsi engineer", "chip design engineer",
            ],
            "related": [
                "Electrical Engineer", "Mechanical Engineer",
                "Manufacturing Engineer",
            ],
        },
        {
            "canonical": "Industrial Engineer",
            "aliases": [
                "industrial engineer",
                "industrial engineering analyst",
                "process improvement engineer",
            ],
            "related": [
                "Mechanical Engineer", "Manufacturing Engineer",
                "Operations Analyst", "Quality Engineer",
            ],
        },
        {
            "canonical": "Manufacturing Engineer",
            "aliases": [
                "manufacturing engineer",
                "manufacturing process engineer",
                "production engineer", "process engineer",
            ],
            "related": [
                "Mechanical Engineer", "Industrial Engineer",
                "Quality Engineer", "Civil Engineer",
            ],
        },
        {
            "canonical": "Quality Engineer",
            "aliases": [
                "quality engineer", "quality assurance engineer",
                "process quality engineer",
                "manufacturing quality engineer",
            ],
            "related": [
                "Mechanical Engineer", "Manufacturing Engineer",
                "Industrial Engineer", "QA Engineer",
            ],
        },
        {
            "canonical": "Project Engineer",
            "aliases": [
                "project engineer",
                "engineering project manager",
                "site project engineer",
            ],
            "related": [
                "Civil Engineer", "Mechanical Engineer",
                "Project Manager", "Site Engineer",
            ],
        },
        {
            "canonical": "Site Engineer",
            "aliases": [
                "site engineer", "site supervisor",
                "construction site engineer",
                "field engineer",
            ],
            "related": [
                "Civil Engineer", "Project Engineer",
                "Construction Engineer",
            ],
        },
    ],
    "Healthcare, Science & Other Professional": [
        {
            "canonical": "Clinical Research Associate",
            "aliases": [
                "clinical research associate",
                "clinical research coordinator",
                "cra", "clinical trial coordinator",
            ],
            "related": [
                "Research Analyst", "Data Analyst",
                "Medical Science Liaison",
            ],
        },
        {
            "canonical": "Medical Science Liaison",
            "aliases": [
                "medical science liaison",
                "msl", "clinical science liaison",
                "medical liaison",
            ],
            "related": [
                "Clinical Research Associate", "Research Scientist",
                "Business Analyst",
            ],
        },
        {
            "canonical": "Research Scientist",
            "aliases": [
                "research scientist", "senior research scientist",
                "scientist", "research fellow",
            ],
            "related": [
                "Data Scientist", "Research Analyst",
                "Clinical Research Associate",
            ],
        },
        {
            "canonical": "Legal Counsel",
            "aliases": [
                "legal counsel", "lawyer", "attorney",
                "senior counsel", "associate counsel",
                "legal advisor", "paralegal",
            ],
            "related": [
                "Compliance Analyst", "Business Analyst",
                "Contract Manager",
            ],
        },
        {
            "canonical": "Consultant",
            "aliases": [
                "consultant", "senior consultant",
                "management consultant", "strategy consultant",
                "it consultant", "technical consultant",
                "business consultant",
            ],
            "related": [
                "Business Analyst", "Project Manager",
                "Solutions Architect", "Business Operations",
            ],
        },
    ],
}

# Flatten into lookup structures.
_CATEGORY_FOR_CANONICAL: dict[str, str] = {}
_CANONICAL_FOR_ALIAS: dict[str, str] = {}
_CANONICAL_TO_RELATED: dict[str, list[str]] = {}

for category, families in _ROLE_TAXONOMY.items():
    for family in families:
        canonical = family["canonical"]
        _CATEGORY_FOR_CANONICAL[canonical] = category
        for alias in family.get("aliases", []):
            _CANONICAL_FOR_ALIAS[alias.lower()] = canonical
        related = family.get("related", [])
        _CANONICAL_TO_RELATED[canonical] = related


def normalize_role(text: str | None) -> str | None:
    """Normalize free-text role input to a canonical role, or None if unknown.

    Uses longest-prefix alias matching with word-boundary awareness so
    "Senior Data Analyst at Risk" correctly maps to "Data Analyst" via the
    "data analyst" alias.
    """
    if not text or not isinstance(text, str):
        return None
    normalized = text.lower().strip()
    
    # Try exact match first.
    if normalized in _CANONICAL_FOR_ALIAS:
        return _CANONICAL_FOR_ALIAS[normalized]
    
    # Try longest substring alias match with word boundaries.
    import re
    best_match: str | None = None
    best_len = 0
    for alias, canonical in _CANONICAL_FOR_ALIAS.items():
        pattern = r'\b' + re.escape(alias) + r'\b'
        if re.search(pattern, normalized) and len(alias) > best_len:
            best_match = canonical
            best_len = len(alias)
    return best_match


def get_category_for_role(canonical_role: str | None) -> str | None:
    """Return the role category for a canonical role, or None."""
    if not canonical_role:
        return None
    return _CATEGORY_FOR_CANONICAL.get(canonical_role)


def get_related_roles(canonical_role: str | None) -> list[str]:
    """Return related canonical roles for controlled expansion."""
    if not canonical_role:
        return []
    return list(_CANONICAL_TO_RELATED.get(canonical_role, []))


def get_all_canonical_roles() -> list[str]:
    """Return all canonical role names."""
    return list(_CATEGORY_FOR_CANONICAL.keys())


def get_all_categories() -> list[str]:
    """Return all role categories."""
    return list(_ROLE_TAXONOMY.keys())
