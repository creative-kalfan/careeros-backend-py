"""Seed Pastry Chef resume for genuine zero-overlap E2E testing.

Creates or resets a Chef Gordon Pastry Chef resume owned by the test user.
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

def seed_pastry_chef() -> dict:
    settings = get_settings()
    test_sb = create_client(settings.supabase_url, settings.supabase_anon_key)
    test_email = os.environ.get("TEST_USER_EMAIL", "careeros-test-user@example.com")
    test_pwd = os.environ.get("TEST_USER_PASSWORD", "")
    
    auth = test_sb.auth.sign_in_with_password({"email": test_email, "password": test_pwd})
    user_id = auth.user.id

    client = get_service_client()

    pastry_profile = {
        "personal": {
            "full_name": "Pastry Chef Gordon",
            "email": "gordon@example.com",
            "phone": "+1 (555) 987-6543",
            "location": "New York, NY",
            "title": "Head Pastry Chef",
        },
        "summary": "Artisanal Pastry Chef with 10 years experience in French patisserie and sourdough fermentation.",
        "skills": {
            "technical": ["Baking", "Pastry Arts", "Sourdough Fermentation", "Recipe Formulation"],
            "tools": ["Convection Oven", "Proofer"],
            "soft_skills": [],
        },
        "experience": [
            {
                "id": str(uuid.uuid4()),
                "company": "Le Petit Bistro",
                "role": "Head Pastry Chef",
                "start_date": "2018-01",
                "end_date": "2024-01",
                "location": "New York, NY",
                "responsibilities": [
                    {"id": str(uuid.uuid4()), "text": "Baked 500+ artisanal loaves and pastries daily for breakfast service."},
                    {"id": str(uuid.uuid4()), "text": "Managed kitchen pantry inventory and ingredient sourcing."},
                ],
                "tools": ["Convection Oven", "Proofer"],
            }
        ],
        "education": [
            {
                "id": str(uuid.uuid4()),
                "institution": "Culinary Institute",
                "degree": "Associate of Arts",
                "field": "Pastry Arts",
                "end_date": "2016-05",
            }
        ],
        "projects": [],
        "certifications": [],
    }

    title = "Chef Gordon - Pastry Chef Resume"
    existing = client.table("resumes").select("id").eq("user_id", user_id).eq("title", title).execute()
    
    if existing.data:
        resume_id = existing.data[0]["id"]
        client.table("resume_versions").delete().eq("resume_id", resume_id).execute()
        client.table("optimization_sessions").delete().eq("resume_id", resume_id).execute()
        client.table("resumes").update({
            "content": {"profile": pastry_profile},
            "parse_status": "completed",
            "original_filename": None,
            "storage_path": None,
        }).eq("id", resume_id).execute()
    else:
        new_res = client.table("resumes").insert({
            "user_id": user_id,
            "title": title,
            "original_filename": None,
            "storage_path": None,
            "parse_status": "completed",
            "content": {"profile": pastry_profile},
        }).execute()
        resume_id = new_res.data[0]["id"]

    master_version_id = str(uuid.uuid4())
    client.table("resume_versions").insert({
        "id": master_version_id,
        "resume_id": resume_id,
        "version_name": "Master Version",
        "is_master": True,
        "source": "manual",
        "content": {"profile": pastry_profile},
    }).execute()

    return {
        "resume_id": resume_id,
        "master_version_id": master_version_id,
        "user_id": user_id,
    }

if __name__ == "__main__":
    result = seed_pastry_chef()
    print(json.dumps(result))
