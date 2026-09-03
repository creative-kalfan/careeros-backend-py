"""Seed deterministic optimization session + suggestions for E2E testing.

Uses the service-role client to bypass RLS and insert directly.
Outputs the resume_id as JSON to stdout for Playwright to consume.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone

# Load backend env
from pathlib import Path

backend_env = Path(__file__).resolve().parent.parent / ".env"
if backend_env.exists():
    for line in backend_env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        idx = line.index("=")
        key, val = line[:idx].strip(), line[idx + 1:].strip()
        os.environ.setdefault(key, val)

from app.db.supabase import get_service_client


RESUME_ID = os.environ.get("SEED_RESUME_ID", "")
JOB_TITLE = "Senior Software Engineer"
COMPANY = "TechCorp Inc"
JOB_DESCRIPTION = (
    "We are looking for a Senior Software Engineer to join our platform team. "
    "Requirements: 5+ years of experience with TypeScript, React, Node.js, Python, "
    "SQL, PostgreSQL, AWS, Docker, Kubernetes. Strong experience with REST APIs, "
    "microservices architecture, CI/CD pipelines, and agile methodologies. "
    "Excellent communication skills and ability to mentor junior developers."
)

SUGGESTION_ID = str(uuid.uuid4())
SESSION_ID = str(uuid.uuid4())


def seed(resume_id: str) -> dict:
    client = get_service_client()

    # Find the resume and its user_id
    resume_resp = (
        client.table("resumes")
        .select("id, user_id, content")
        .eq("id", resume_id)
        .limit(1)
        .execute()
    )
    if not resume_resp.data:
        print(f"ERROR: Resume {resume_id} not found", file=sys.stderr)
        sys.exit(1)

    resume = resume_resp.data[0]
    user_id = resume["user_id"]

    # Find or create a master version
    versions_resp = (
        client.table("resume_versions")
        .select("id")
        .eq("resume_id", resume_id)
        .eq("is_master", True)
        .limit(1)
        .execute()
    )
    version_id = versions_resp.data[0]["id"] if versions_resp.data else None
    if not version_id:
        v_id = str(uuid.uuid4())
        client.table("resume_versions").insert({
            "id": v_id,
            "resume_id": resume_id,
            "version_name": "Master Version",
            "is_master": True,
            "source": "upload_parse",
            "content": resume.get("content") or {},
        }).execute()
        version_id = v_id

    # Delete any existing seeded sessions for this resume (idempotent)
    existing = (
        client.table("optimization_sessions")
        .select("id")
        .eq("resume_id", resume_id)
        .execute()
    )
    for sess in (existing.data or []):
        # Delete suggestions first
        client.table("optimization_suggestions").delete().eq(
            "session_id", sess["id"]
        ).execute()
        client.table("optimization_sessions").delete().eq("id", sess["id"]).execute()

    # Create session
    now = datetime.now(timezone.utc).isoformat()
    session_row = {
        "id": SESSION_ID,
        "resume_id": resume_id,
        "version_id": version_id,
        "job_title": JOB_TITLE,
        "company": COMPANY,
        "job_description": JOB_DESCRIPTION,
        "status": "active",
        "suggestions_generated": 2,
        "suggestions_accepted": 0,
        "suggestions_rejected": 0,
        "target_job_title": JOB_TITLE,
        "target_company": COMPANY,
        "created_at": now,
        "updated_at": now,
    }
    client.table("optimization_sessions").insert(session_row).execute()

    # Suggestion 1: professional_summary replacement
    suggestion_1 = {
        "id": SUGGESTION_ID,
        "type": "professional_summary",
        "priority": "high",
        "section": "summary",
        "entry_id": None,
        "child_id": None,
        "current_text": "Experienced software engineer with a passion for building great products.",
        "suggested_text": (
            "Senior Software Engineer with 6+ years of experience building scalable "
            "web applications using TypeScript, React, and Node.js. Proven track record "
            "of delivering production-grade microservices on AWS with Docker and Kubernetes. "
            "Strong communicator and mentor to junior developers."
        ),
        "explanation": (
            "The current summary is too generic. The target role requires specific "
            "mention of TypeScript, React, Node.js, AWS, and leadership experience. "
            "Adding quantified experience and relevant technologies improves ATS matching."
        ),
        "evidence": [
            "TypeScript experience mentioned in resume",
            "React projects listed",
            "Node.js backend work documented",
            "AWS deployment experience present",
        ],
        "affected_keywords": ["TypeScript", "React", "Node.js", "AWS", "microservices"],
        "category": None,
        "action": None,
        "skill": None,
        "similar_in_resume": None,
        "status": "pending",
        "evidence_issues": [],
        "created_at": now,
        "updated_at": now,
    }

    # Suggestion 2: skills alignment
    suggestion_2_id = str(uuid.uuid4())
    suggestion_2 = {
        "id": suggestion_2_id,
        "type": "skills_alignment",
        "priority": "medium",
        "section": "skills",
        "entry_id": None,
        "child_id": None,
        "current_text": None,
        "suggested_text": None,
        "explanation": (
            "Kubernetes is listed in the job requirements but not prominently featured "
            "in your skills section. Consider adding it to improve keyword matching."
        ),
        "evidence": [
            "Kubernetes mentioned in job description",
            "Docker experience present in resume",
        ],
        "affected_keywords": ["Kubernetes"],
        "category": "missing_without_evidence",
        "action": "verify",
        "skill": "Kubernetes",
        "similar_in_resume": "Docker",
        "status": "pending",
        "evidence_issues": [],
        "created_at": now,
        "updated_at": now,
    }

    # Insert suggestion records (the table stores the full dict in JSONB `suggestion` column)
    for sug in [suggestion_1, suggestion_2]:
        record = {
            "id": sug["id"],
            "session_id": SESSION_ID,
            "suggestion": sug,
            "resume_snapshot": resume.get("content"),
            "applied": False,
            "created_at": now,
            "updated_at": now,
        }
        client.table("optimization_suggestions").insert(record).execute()

    result = {
        "resume_id": resume_id,
        "session_id": SESSION_ID,
        "suggestion_id": SUGGESTION_ID,
        "user_id": user_id,
    }
    return result


if __name__ == "__main__":
    resume_id = RESUME_ID
    if not resume_id:
        # Find a resume with actual content owned by the test user
        client = get_service_client()
        # Sign in as test user to get user_id
        settings = __import__("app.config", fromlist=["get_settings"]).get_settings()
        test_sb = __import__("supabase", fromlist=["create_client"]).create_client(
            settings.supabase_url, settings.supabase_anon_key
        )
        test_email = os.environ.get("TEST_USER_EMAIL", "test-user@example.com")
        test_pwd = os.environ.get("TEST_USER_PASSWORD", "")
        auth = test_sb.auth.sign_in_with_password(
            {"email": test_email, "password": test_pwd}
        )
        test_user_id = auth.user.id
        # Find resumes owned by test user with content
        resp = (
            client.table("resumes")
            .select("id, content")
            .eq("user_id", test_user_id)
            .execute()
        )
        resume_id = None
        for r in (resp.data or []):
            content = r.get("content") or {}
            if content and content.get("profile"):
                resume_id = r["id"]
                break
        if not resume_id:
            print("ERROR: No resumes with content found for test user", file=sys.stderr)
            sys.exit(1)

    result = seed(resume_id)
    print(json.dumps(result))
