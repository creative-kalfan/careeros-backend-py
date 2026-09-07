"""Seed the real DMX incident resume into Supabase for Playwright E2E verification."""

import json
import uuid
from pathlib import Path

from app.db.supabase import get_service_client
from app.services.resume_parser.pdf_parser import PDFParser
from app.services.resume_parser.adapters import parsed_resume_to_resume_content
from app.services.resumes.compiler_service import resume_compiler_service
from app.services.resumes.document_model import build_document_model
from app.services.resumes.docx_compiler import docx_compiler
from app.services.resumes.pdf_compiler import pdf_compiler

def seed_dmx_resume():
    client = get_service_client()
    user_id = "f2fb4d3a-4c02-454c-85b2-c2efde29d011"

    pdf_path = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "real_resumes" / "real_incident_dmx_technologies.pdf"
    parser = PDFParser()
    res = parser.parse(pdf_path.read_bytes())
    content = parsed_resume_to_resume_content(res.parsed)

    # Clean up any existing test resume with this title
    existing = client.table("resumes").select("id").eq("user_id", user_id).eq("title", "Pathan Mohammad Kalfan - Resume").execute()
    for r in (existing.data or []):
        r_id = r["id"]
        client.table("resume_versions").delete().eq("resume_id", r_id).execute()
        client.table("resumes").delete().eq("id", r_id).execute()

    resume_id = str(uuid.uuid4())
    version_id = str(uuid.uuid4())

    doc_model = build_document_model(content, res.geometry)
    docx_bytes = docx_compiler.compile(doc_model)
    compiled_pdf, _ = pdf_compiler.compile(doc_model, docx_bytes)

    # Upload compiled PDF to storage
    storage_path = f"{user_id}/versions/{version_id}.pdf"
    try:
        client.storage.from_("resumes").upload(
            path=storage_path,
            file=compiled_pdf,
            file_options={"content-type": "application/pdf", "upsert": "true"},
        )
    except Exception as e:
        print(f"Storage upload note: {e}")

    content_dict = content.to_dict()

    client.table("resumes").insert({
        "id": resume_id,
        "user_id": user_id,
        "title": "Pathan Mohammad Kalfan - Resume",
        "original_filename": "real_incident_dmx_technologies.pdf",
        "content": content_dict,
        "parse_status": "completed",
    }).execute()

    client.table("resume_versions").insert({
        "id": version_id,
        "resume_id": resume_id,
        "version_name": "Master Version",
        "is_master": True,
        "source": "upload_parse",
        "content": content_dict,
        "meta": {"storage_path": storage_path},
    }).execute()

    print(json.dumps({"resume_id": resume_id, "version_id": version_id}))
    return resume_id, version_id

if __name__ == "__main__":
    seed_dmx_resume()
