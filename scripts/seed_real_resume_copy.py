"""Seed a copy of the real NOC resume (5b3a6ea9) under the test user for UI E2E."""
import json, os, uuid
from pathlib import Path

backend_env = Path(__file__).resolve().parent.parent / ".env"
if backend_env.exists():
    for line in backend_env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        idx = line.index("=")
        os.environ.setdefault(line[:idx].strip(), line[idx+1:].strip())

from app.config import get_settings
from app.db.supabase import get_service_client
from supabase import create_client

SRC_RESUME_ID = os.environ.get("SEED_SOURCE_RESUME_ID", "5b3a6ea9-b633-4eec-9a41-c6b0e24748a9")


def seed() -> dict:
    settings = get_settings()
    anon = create_client(settings.supabase_url, settings.supabase_anon_key)
    email = os.environ.get("TEST_USER_EMAIL", "careeros-test-user@example.com")
    pwd = os.environ.get("TEST_USER_PASSWORD", "")
    auth = anon.auth.sign_in_with_password({"email": email, "password": pwd})
    user_id = auth.user.id

    service = get_service_client()
    src = service.table("resumes").select("content").eq("id", SRC_RESUME_ID).execute()
    content = src.data[0]["content"]

    created = service.table("resumes").insert({
        "user_id": user_id,
        "title": "__E2E_REPRO__ NOC resume copy",
        "original_filename": None,
        "storage_path": None,
        "parse_status": "completed",
        "content": content,
    }).execute()
    resume_id = created.data[0]["id"]

    src_master = service.table("resume_versions").select("*").eq("resume_id", SRC_RESUME_ID).eq("is_master", True).execute()
    master_geom = (src_master.data[0].get("meta") or {}).get("geometry")
    master_vid = str(uuid.uuid4())
    service.table("resume_versions").insert({
        "id": master_vid, "resume_id": resume_id, "version_name": "Master Version",
        "is_master": True, "source": "manual", "content": content,
        "meta": {"geometry": master_geom},
    }).execute()

    return {"resume_id": resume_id, "master_version_id": master_vid, "user_id": user_id}


if __name__ == "__main__":
    print(json.dumps(seed()))