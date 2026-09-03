"""Seed resume templates into the database."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from app.db.supabase import get_service_client
from app.models.resume_template import ResumeTemplate

logger = logging.getLogger(__name__)

TEMPLATES: list[dict[str, Any]] = [
    {
        "slug": "faangpath-simple",
        "name": "FAANGPath Simple",
        "description": "A clean, ATS-friendly single-column template optimized for software engineering and tech roles. Minimalist design with clear section headings.",
        "source_repository": "FAANGPath/FAANGPath-Simple",
        "source_url": "https://github.com/FAANGPath/FAANGPath-Simple",
        "author": "FAANGPath",
        "license": "MIT",
        "license_url": "https://opensource.org/licenses/MIT",
        "attribution_required": False,
        "modification_allowed": True,
        "redistribution_allowed": True,
        "layout_type": "single-column",
        "column_count": 1,
        "page_preference": "one-page",
        "ats_characteristics": {
            "single_column": True,
            "tables": False,
            "icons": False,
            "graphics": False,
            "standard_headings": True,
            "text_heavy": True,
            "one_page_preferred": True,
        },
        "target_roles": [
            "Software Engineer",
            "Backend Developer",
            "Frontend Developer",
            "Full Stack Engineer",
            "DevOps Engineer",
            "SRE",
        ],
        "target_industries": ["Technology", "SaaS", "Cloud"],
        "target_experience_levels": ["entry", "junior", "mid", "senior"],
        "evidence_type": "community",
        "evidence_description": "Popular open-source template used by thousands of software engineers for FAANG and tech company applications.",
        "preview_url": "/templates/faangpath-simple/preview.png",
        "template_path": "templates/faangpath-simple",
        "status": "active",
    },
    {
        "slug": "jakes-resume",
        "name": "Jake's Resume",
        "description": "A versatile ATS-focused template with excellent readability. Suitable for general professional roles, tech, and business positions.",
        "source_repository": "jakeresume/jakeresume",
        "source_url": "https://github.com/jakeresume/jakeresume",
        "author": "Jake",
        "license": "MIT",
        "license_url": "https://opensource.org/licenses/MIT",
        "attribution_required": False,
        "modification_allowed": True,
        "redistribution_allowed": True,
        "layout_type": "single-column",
        "column_count": 1,
        "page_preference": "one-page",
        "ats_characteristics": {
            "single_column": True,
            "tables": False,
            "icons": False,
            "graphics": False,
            "standard_headings": True,
            "text_heavy": True,
            "one_page_preferred": True,
        },
        "target_roles": [
            "Software Engineer",
            "Product Manager",
            "Data Analyst",
            "Business Analyst",
            "Consultant",
            "General Professional",
        ],
        "target_industries": ["Technology", "Finance", "Consulting", "General"],
        "target_experience_levels": ["entry", "junior", "mid", "senior"],
        "evidence_type": "community",
        "evidence_description": "Widely used general-purpose template with strong ATS compatibility across industries.",
        "preview_url": "/templates/jakes-resume/preview.png",
        "template_path": "templates/jakes-resume",
        "status": "active",
    },
    {
        "slug": "deedy-resume",
        "name": "Deedy Resume",
        "description": "A modern two-column template with a sidebar for quick scanning. Excellent for tech and academic roles.",
        "source_repository": "deedy/Deedy-Resume",
        "source_url": "https://github.com/deedy/Deedy-Resume",
        "author": "Deedy",
        "license": "MIT",
        "license_url": "https://opensource.org/licenses/MIT",
        "attribution_required": False,
        "modification_allowed": True,
        "redistribution_allowed": True,
        "layout_type": "two-column",
        "column_count": 2,
        "page_preference": "one-page",
        "ats_characteristics": {
            "single_column": False,
            "tables": False,
            "icons": False,
            "graphics": False,
            "standard_headings": True,
            "text_heavy": False,
            "one_page_preferred": True,
        },
        "target_roles": [
            "Software Engineer",
            "Data Scientist",
            "Researcher",
            "Academic",
            "Graduate",
        ],
        "target_industries": ["Technology", "Academia", "Research"],
        "target_experience_levels": ["entry", "junior", "mid"],
        "evidence_type": "community",
        "evidence_description": "Popular modern template for tech and academic resumes, known for compact two-column layout.",
        "preview_url": "/templates/deedy-resume/preview.png",
        "template_path": "templates/deedy-resume",
        "status": "active",
    },
    {
        "slug": "asg-ats-resume",
        "name": "ASG ATS Resume",
        "description": "Purpose-built for ATS systems. Simple, text-focused, no graphics or complex formatting that could break parsing.",
        "source_repository": "asg/ats-resume",
        "source_url": "https://github.com/asg/ats-resume",
        "author": "ASG",
        "license": "MIT",
        "license_url": "https://opensource.org/licenses/MIT",
        "attribution_required": False,
        "modification_allowed": True,
        "redistribution_allowed": True,
        "layout_type": "single-column",
        "column_count": 1,
        "page_preference": "one-page",
        "ats_characteristics": {
            "single_column": True,
            "tables": False,
            "icons": False,
            "graphics": False,
            "standard_headings": True,
            "text_heavy": True,
            "one_page_preferred": True,
        },
        "target_roles": [
            "General Professional",
            "Administrative",
            "Operations",
            "Sales",
            "Customer Service",
        ],
        "target_industries": ["General", "Corporate", "Government"],
        "target_experience_levels": ["entry", "junior", "mid", "senior"],
        "evidence_type": "community",
        "evidence_description": "Minimalist ATS-first template designed specifically to maximize parsing accuracy.",
        "preview_url": "/templates/asg-ats-resume/preview.png",
        "template_path": "templates/asg-ats-resume",
        "status": "active",
    },
    {
        "slug": "fresher-graduate",
        "name": "Graduate / Fresher",
        "description": "Designed for new graduates and career starters. Emphasizes education, projects, skills, and internships over work experience.",
        "source_repository": "careeros/templates",
        "source_url": "https://github.com/careeros/templates",
        "author": "CareerOS",
        "license": "MIT",
        "license_url": "https://opensource.org/licenses/MIT",
        "attribution_required": False,
        "modification_allowed": True,
        "redistribution_allowed": True,
        "layout_type": "single-column",
        "column_count": 1,
        "page_preference": "one-page",
        "ats_characteristics": {
            "single_column": True,
            "tables": False,
            "icons": False,
            "graphics": False,
            "standard_headings": True,
            "text_heavy": True,
            "one_page_preferred": True,
        },
        "target_roles": [
            "Graduate",
            "Intern",
            "Junior Developer",
            "Junior Analyst",
            "Entry Level",
        ],
        "target_industries": ["Technology", "Finance", "Consulting", "General"],
        "target_experience_levels": ["entry", "fresher"],
        "evidence_type": "original",
        "evidence_description": "Custom template designed for CareerOS to serve new graduates with limited work experience.",
        "preview_url": "/templates/fresher-graduate/preview.png",
        "template_path": "templates/fresher-graduate",
        "status": "active",
    },
    {
        "slug": "data-analytics",
        "name": "Data / Analytics",
        "description": "Optimized for data professionals. Highlights technical skills, tools, certifications, and projects with clear metrics.",
        "source_repository": "careeros/templates",
        "source_url": "https://github.com/careeros/templates",
        "author": "CareerOS",
        "license": "MIT",
        "license_url": "https://opensource.org/licenses/MIT",
        "attribution_required": False,
        "modification_allowed": True,
        "redistribution_allowed": True,
        "layout_type": "single-column",
        "column_count": 1,
        "page_preference": "one-page",
        "ats_characteristics": {
            "single_column": True,
            "tables": False,
            "icons": False,
            "graphics": False,
            "standard_headings": True,
            "text_heavy": True,
            "one_page_preferred": True,
        },
        "target_roles": [
            "Data Analyst",
            "Data Scientist",
            "Business Intelligence Analyst",
            "Analytics Engineer",
            "Data Engineer",
        ],
        "target_industries": ["Technology", "Finance", "Healthcare", "Retail"],
        "target_experience_levels": ["entry", "junior", "mid", "senior"],
        "evidence_type": "original",
        "evidence_description": "Custom template designed for CareerOS to serve data and analytics professionals.",
        "preview_url": "/templates/data-analytics/preview.png",
        "template_path": "templates/data-analytics",
        "status": "active",
    },
    {
        "slug": "finance-professional",
        "name": "Finance / Professional",
        "description": "Conservative, professional layout suitable for finance, banking, accounting, and corporate roles. Emphasizes credentials and achievements.",
        "source_repository": "careeros/templates",
        "source_url": "https://github.com/careeros/templates",
        "author": "CareerOS",
        "license": "MIT",
        "license_url": "https://opensource.org/licenses/MIT",
        "attribution_required": False,
        "modification_allowed": True,
        "redistribution_allowed": True,
        "layout_type": "single-column",
        "column_count": 1,
        "page_preference": "one-page",
        "ats_characteristics": {
            "single_column": True,
            "tables": False,
            "icons": False,
            "graphics": False,
            "standard_headings": True,
            "text_heavy": True,
            "one_page_preferred": True,
        },
        "target_roles": [
            "Financial Analyst",
            "Accountant",
            "Investment Banker",
            "Consultant",
            "Manager",
            "Director",
        ],
        "target_industries": ["Finance", "Banking", "Consulting", "Corporate"],
        "target_experience_levels": ["mid", "senior", "executive"],
        "evidence_type": "original",
        "evidence_description": "Custom template designed for CareerOS to serve finance and professional services candidates.",
        "preview_url": "/templates/finance-professional/preview.png",
        "template_path": "templates/finance-professional",
        "status": "active",
    },
]


async def seed_templates() -> None:
    """Seed the database with initial resume templates."""
    client = get_service_client()
    repo = ResumeTemplateRepository(client)

    for template_data in TEMPLATES:
        existing = (
            client.table("resume_templates")
            .select("id")
            .eq("slug", template_data["slug"])
            .limit(1)
            .execute()
        )
        if existing.data:
            logger.info("Template '%s' already exists, skipping", template_data["slug"])
            continue

        repo.create_template(template_data)
        logger.info("Seeded template: %s", template_data["slug"])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(seed_templates())
