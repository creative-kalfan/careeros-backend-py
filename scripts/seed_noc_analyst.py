"""Seed NOC Analyst resume for domain-gap E2E testing.

Creates or resets an Alex Chen NOC Analyst resume owned by the test user.
Outputs JSON with resume_id to stdout.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

# Load backend env
backend_env = Path(__file__).resolve().parent.parent / ".env"
if backend_env.exists():
    for line in backend_env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        idx = line.index("=")
        key, val = line[:idx].strip(), line[idx + 1:].strip()
        os.environ.setdefault(key, val)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.supabase import get_service_client
from app.config import get_settings
from supabase import create_client

def seed_noc_analyst() -> dict:
    settings = get_settings()
    test_sb = create_client(settings.supabase_url, settings.supabase_anon_key)
    test_email = os.environ.get("TEST_USER_EMAIL", "careeros-test-user@example.com")
    test_pwd = os.environ.get("TEST_USER_PASSWORD", "")
    
    auth = test_sb.auth.sign_in_with_password({"email": test_email, "password": test_pwd})
    user_id = auth.user.id

    client = get_service_client()

    noc_profile = {
        "personal": {
            "full_name": "Alex Chen",
            "email": "alex.chen@example.com",
            "phone": "+1 (555) 123-4567",
            "location": "Chicago, IL",
            "title": "NOC Analyst",
        },
        "summary": "Network Operations Center (NOC) Analyst with 4 years managing enterprise systems, following SOP guidelines, and generating operational reports.",
        "skills": {
            "technical": ["Network Monitoring", "Linux", "SOP Adherence", "Incident Management", "Process Documentation"],
            "tools": ["Wireshark", "JIRA", "Pingdom"],
            "soft_skills": ["Cross-Functional Collaboration", "Operational Reporting", "Problem Solving"],
        },
        "experience": [
            {
                "id": str(uuid.uuid4()),
                "company": "CloudTech Global",
                "role": "NOC Analyst",
                "start_date": "2020-06",
                "end_date": "2024-06",
                "location": "Chicago, IL",
                "responsibilities": [
                    {"id": str(uuid.uuid4()), "text": "Maintained rigorous SOP adherence and operational documentation for all incident workflows."},
                    {"id": str(uuid.uuid4()), "text": "Generated weekly operational reporting and metrics for leadership reviews."},
                    {"id": str(uuid.uuid4()), "text": "Fostered cross-functional collaboration between engineering and support teams to resolve issues."},
                ],
                "tools": ["JIRA", "Linux"],
            }
        ],
        "education": [
            {
                "id": str(uuid.uuid4()),
                "institution": "University of Illinois",
                "degree": "Bachelor of Science",
                "field": "Information Technology",
                "end_date": "2020-05",
            }
        ],
        "projects": [],
        "certifications": [],
    }

    # Check for existing resume with title "Alex Chen - NOC Analyst Resume"
    existing = client.table("resumes").select("id").eq("user_id", user_id).eq("title", "Alex Chen - NOC Analyst Resume").execute()
    
    if existing.data:
        resume_id = existing.data[0]["id"]
        # Clean up existing versions, sessions
        client.table("resume_versions").delete().eq("resume_id", resume_id).execute()
        client.table("optimization_sessions").delete().eq("resume_id", resume_id).execute()
        client.table("resumes").update({
            "content": {"profile": noc_profile},
            "parse_status": "completed",
            "original_filename": None,
            "storage_path": None,
        }).eq("id", resume_id).execute()
    else:
        new_res = client.table("resumes").insert({
            "user_id": user_id,
            "title": "Alex Chen - NOC Analyst Resume",
            "original_filename": None,
            "storage_path": None,
            "parse_status": "completed",
            "content": {"profile": noc_profile},
        }).execute()
        resume_id = new_res.data[0]["id"]

    # Insert Master Version
    master_version_id = str(uuid.uuid4())
    client.table("resume_versions").insert({
        "id": master_version_id,
        "resume_id": resume_id,
        "version_name": "Master Version",
        "is_master": True,
        "source": "manual",
        "content": {"profile": noc_profile},
    }).execute()

    return {
        "resume_id": resume_id,
        "master_version_id": master_version_id,
        "user_id": user_id,
    }

if __name__ == "__main__":
    result = seed_noc_analyst()
    print(json.dumps(result))
