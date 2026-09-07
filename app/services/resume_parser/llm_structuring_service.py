"""LLM-based Resume Structuring Service.

Reads full raw resume text and produces a high-fidelity structured JSON representation
in a single context-aware LLM pass. Replaces brittle regex / heuristic parsing.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from app.llm.gateway import get_llm_gateway
from app.llm.sync_bridge import run_coro_sync
from app.llm.types import LLMRequest, LLMTask
from .models import (
    ParsedContact,
    ParsedEducation,
    ParsedExperience,
    ParsedProject,
    ParsedResume,
)

logger = logging.getLogger(__name__)


class LLMStructuringService:
    """Extracts structured resume data from raw text using a single context-aware LLM call."""

    SYSTEM_INSTRUCTION = (
        "You are an expert resume parsing engine.\n"
        "Your task is to parse the complete raw resume text into a structured JSON representation.\n"
        "STRICT EXTRACTION RULES:\n"
        "1. Extract the candidate's personal contact info (name, email, phone, location, links). Preserve the exact casing of the candidate's name as written in the source text (e.g. ALL CAPS if all caps in source).\n"
        "2. Experience: Extract every distinct job entry with company, role/title, dates, location, and responsibilities.\n"
        "3. Nested Sub-Engagements: If an experience role contains sub-projects, client engagements, or live application testing contributions under it (e.g. specific project names like Syntheseed.com, LearnSquare with their own bullets), keep them genuinely nested under that experience entry in `sub_engagements` with `name` and `bullets`.\n"
        "4. Skills: Preserve every explicit skill category label the source resume uses (e.g., 'Manual Testing', 'Test Execution', 'Defect Management', 'Platforms', 'Tools', 'Methodologies') as keys in a dictionary under `skills_categories`.\n"
        "5. Education: Extract institution, degree, field/specialization (e.g., 'Civil Engineering'), dates, GPA/CGPA (e.g., 'CGPA: 7.5'), and coursework.\n"
        "6. Additional sections: Extract any additional knowledge, certifications, achievements, or languages into their respective fields.\n"
        "7. NEVER omit or invent details. Ground every field strictly in the source text.\n"
        "8. Output ONLY a valid JSON object matching the requested schema."
    )

    def structure_resume_text(self, raw_text: str) -> ParsedResume:
        """Call LLM to parse raw resume text into a structured ParsedResume object."""
        if not raw_text or not raw_text.strip():
            raise ValueError("Raw resume text is empty")

        prompt = (
            "Parse the following resume text into structured JSON format:\n\n"
            "```json\n"
            "{\n"
            '  "contact": {\n'
            '    "name": "Candidate Full Name",\n'
            '    "email": "email@example.com",\n'
            '    "phone": "+1 ...",\n'
            '    "location": "City, Country",\n'
            '    "headline": "Headline if present",\n'
            '    "linkedin": "url or profile",\n'
            '    "github": "url or profile",\n'
            '    "website": "url"\n'
            "  },\n"
            '  "summary": "Professional summary if present",\n'
            '  "skills_categories": {\n'
            '    "Category Name 1": ["Skill 1", "Skill 2"],\n'
            '    "Category Name 2": ["Skill 3", "Skill 4"]\n'
            "  },\n"
            '  "experience": [\n'
            "    {\n"
            '      "company": "Company Name",\n'
            '      "title": "Job Title / Role",\n'
            '      "location": "Location",\n'
            '      "start_date": "Start Date",\n'
            '      "end_date": "End Date or Present",\n'
            '      "bullets": ["Main bullet 1", "Main bullet 2"],\n'
            '      "sub_engagements": [\n'
            "        {\n"
            '          "name": "Sub-project / Live App / Client Name",\n'
            '          "description": "Optional description",\n'
            '          "bullets": ["Sub-bullet 1", "Sub-bullet 2"]\n'
            "        }\n"
            "      ]\n"
            "    }\n"
            "  ],\n"
            '  "education": [\n'
            "    {\n"
            '      "institution": "University / College Name",\n'
            '      "degree": "Degree (e.g. B.Tech, B.S.)",\n'
            '      "field": "Major / Field of Study (e.g. Civil Engineering)",\n'
            '      "start_date": "Start Year/Date",\n'
            '      "end_date": "End Year/Date",\n'
            '      "gpa": "GPA or CGPA if present",\n'
            '      "coursework": []\n'
            "    }\n"
            "  ],\n"
            '  "projects": [\n'
            "    {\n"
            '      "name": "Independent Project Name",\n'
            '      "description": "Description",\n'
            '      "bullets": ["Bullet 1"]\n'
            "    }\n"
            "  ],\n"
            '  "additional": ["Additional knowledge / tools / info item 1"],\n'
            '  "certifications": ["Certification 1"],\n'
            '  "achievements": ["Achievement 1"],\n'
            '  "languages": ["Language 1"]\n'
            "}\n"
            "```\n\n"
            f"SOURCE RESUME TEXT:\n{raw_text}\n"
        )

        gateway = get_llm_gateway()
        response = run_coro_sync(
            gateway.generate(
                LLMRequest(
                    task=LLMTask.RESUME_SECTION_SUGGESTION,
                    prompt=prompt,
                    system_instruction=self.SYSTEM_INSTRUCTION,
                    temperature=0.1,
                    max_tokens=4096,
                )
            ),
            timeout_seconds=35.0,
        )

        content_str = response.content.strip()
        if content_str.startswith("```"):
            content_str = re.sub(r"^```(?:json)?\n?", "", content_str)
            content_str = re.sub(r"\n?```$", "", content_str)

        data = json.loads(content_str)
        if not isinstance(data, dict):
            raise ValueError(f"LLM returned non-dictionary root JSON: {type(data)}")

        return self._json_to_parsed_resume(data, raw_text)

    def _json_to_parsed_resume(self, data: dict[str, Any], raw_text: str) -> ParsedResume:
        contact_data = data.get("contact") or {}
        contact = ParsedContact(
            name=contact_data.get("name") or None,
            email=contact_data.get("email") or None,
            phone=contact_data.get("phone") or None,
            location=contact_data.get("location") or None,
            linkedin=contact_data.get("linkedin") or None,
            github=contact_data.get("github") or None,
            website=contact_data.get("website") or None,
        )

        summary = data.get("summary")
        if isinstance(summary, str) and not summary.strip():
            summary = None

        # Experience entries
        experience_list: list[ParsedExperience] = []
        for exp in data.get("experience") or []:
            if not isinstance(exp, dict):
                continue
            bullets = [str(b).strip() for b in (exp.get("bullets") or []) if str(b).strip()]
            sub_engagements: list[ParsedProject] = []
            for sub in exp.get("sub_engagements") or []:
                if isinstance(sub, dict):
                    s_name = str(sub.get("name") or "").strip()
                    s_desc = str(sub.get("description") or "").strip()
                    s_bullets = [str(b).strip() for b in (sub.get("bullets") or []) if str(b).strip()]
                    if s_name:
                        sub_engagements.append(
                            ParsedProject(
                                name=s_name,
                                description=s_desc,
                                bullets=s_bullets,
                                confidence="high",
                            )
                        )
            experience_list.append(
                ParsedExperience(
                    title=str(exp.get("title") or "").strip(),
                    company=str(exp.get("company") or "").strip(),
                    location=exp.get("location"),
                    start_date=exp.get("start_date"),
                    end_date=exp.get("end_date"),
                    bullets=bullets,
                    sub_engagements=sub_engagements,
                    confidence="high",
                )
            )

        # Education entries
        education_list: list[ParsedEducation] = []
        for edu in data.get("education") or []:
            if not isinstance(edu, dict):
                continue
            education_list.append(
                ParsedEducation(
                    degree=str(edu.get("degree") or "").strip(),
                    field=str(edu.get("field") or "").strip() or None,
                    institution=str(edu.get("institution") or "").strip(),
                    start_date=edu.get("start_date"),
                    end_date=edu.get("end_date"),
                    gpa=edu.get("gpa"),
                    confidence="high",
                )
            )

        # Skills and Categories
        skill_categories: dict[str, list[str]] = {}
        all_skills: list[str] = []
        raw_cats = data.get("skills_categories") or data.get("skills") or {}
        if isinstance(raw_cats, dict):
            for cat_name, skill_items in raw_cats.items():
                if isinstance(skill_items, list):
                    clean_skills = [str(s).strip() for s in skill_items if str(s).strip()]
                    if clean_skills:
                        skill_categories[cat_name] = clean_skills
                        for s in clean_skills:
                            if s not in all_skills:
                                all_skills.append(s)
        elif isinstance(raw_cats, list):
            all_skills = [str(s).strip() for s in raw_cats if str(s).strip()]

        # Projects
        projects_list: list[ParsedProject] = []
        for prj in data.get("projects") or []:
            if isinstance(prj, dict) and prj.get("name"):
                projects_list.append(
                    ParsedProject(
                        name=str(prj.get("name") or "").strip(),
                        description=str(prj.get("description") or "").strip(),
                        bullets=[str(b).strip() for b in (prj.get("bullets") or []) if str(b).strip()],
                        confidence="high",
                    )
                )

        # Additional
        additional_list: list[str] = []
        for a in data.get("additional") or []:
            if isinstance(a, str) and a.strip():
                additional_list.append(a.strip())
            elif isinstance(a, dict) and a.get("description"):
                additional_list.append(str(a.get("description")).strip())

        certifications = [str(c).strip() for c in (data.get("certifications") or []) if str(c).strip()]
        achievements = [str(a).strip() for a in (data.get("achievements") or []) if str(a).strip()]
        languages = [str(l).strip() for l in (data.get("languages") or []) if str(l).strip()]
        links = [str(l).strip() for l in (data.get("links") or []) if str(l).strip()]

        return ParsedResume(
            contact=contact,
            summary=summary,
            experience=experience_list,
            education=education_list,
            skills=all_skills,
            skill_categories=skill_categories,
            projects=projects_list,
            certifications=certifications,
            achievements=achievements,
            languages=languages,
            links=links,
            additional=additional_list,
            raw_text=raw_text,
            parse_notes=["Parsed by LLMStructuringService (one-pass context-aware)"],
        )


llm_structuring_service = LLMStructuringService()
