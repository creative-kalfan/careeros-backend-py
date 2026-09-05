"""Canonical Resume Document Compiler Service for CareerOS.

Coordinates the complete document pipeline:
Semantic Model + Style Model -> Native Editable DOCX -> Converted PDF ->
Visual Verification -> Storage Persistence -> Geometry Synchronization.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Optional, Tuple

import fitz  # PyMuPDF

from app.db.supabase import get_authenticated_client, get_service_client
from app.models.resume import ResumeContent
from app.services.resume_parser.geometry import extract_document_geometry
from .document_model import ResumeDocumentModel, build_document_model
from .docx_compiler import docx_compiler
from .pdf_compiler import pdf_compiler
from .fit_verifier import fit_verifier
from .pdf_mutation import PDFMutationEngine
from .visual_verification import VisualVerificationEngine, VisualVerificationResult

logger = logging.getLogger(__name__)


def _upload_to_storage(
    storage_path: str,
    data_bytes: bytes,
    content_type: str,
    jwt: Optional[str] = None,
) -> bool:
    """Upload artifact bytes to Supabase Storage resumes bucket."""
    file_opts = {"content-type": content_type, "upsert": "true"}
    if jwt:
        try:
            client = get_authenticated_client(jwt)
            client.storage.from_("resumes").upload(storage_path, data_bytes, file_options=file_opts)
            return True
        except Exception as e:
            logger.warning("Authenticated storage upload failed (%s); trying service client", e)

    try:
        service_client = get_service_client()
        service_client.storage.from_("resumes").upload(storage_path, data_bytes, file_options=file_opts)
        return True
    except Exception as e:
        logger.error("Service client storage upload failed for %s: %s", storage_path, e)
        return False


def _download_from_storage(storage_path: str, jwt: Optional[str] = None) -> Optional[bytes]:
    """Download artifact bytes from Supabase Storage resumes bucket."""
    if jwt:
        try:
            client = get_authenticated_client(jwt)
            return client.storage.from_("resumes").download(storage_path)
        except Exception:
            pass
    try:
        service_client = get_service_client()
        return service_client.storage.from_("resumes").download(storage_path)
    except Exception as e:
        logger.error("Failed to download %s from storage: %s", storage_path, e)
        return None


class ResumeCompilerService:
    """High-level compiler service coordinating native DOCX and PDF generation."""

    def compile_and_persist(
        self,
        user_id: str,
        version_id: str,
        content: ResumeContent,
        geometry_map: Optional[dict[str, Any]] = None,
        jwt: Optional[str] = None,
        prefer_direct_mutation: bool = False,
        mutation_source_path: Optional[str] = None,
        mutation_params: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Compile and persist real versioned DOCX and PDF artifacts to storage."""
        # 1. Direct PDF Mutation Strategy (Pipeline A) for small inline edits
        if prefer_direct_mutation and mutation_source_path and mutation_params:
            try:
                pdf_bytes = _download_from_storage(mutation_source_path, jwt=jwt)
                if pdf_bytes:
                    mutated_pdf, updated_geom = PDFMutationEngine.mutate(
                        pdf_bytes=pdf_bytes,
                        page_index=mutation_params.get("page_index", 0),
                        bbox=mutation_params.get("bbox", []),
                        replacement_text=mutation_params.get("replacement_text", ""),
                        font_name=mutation_params.get("font_name"),
                        font_size=mutation_params.get("font_size"),
                        is_bold=mutation_params.get("is_bold", False),
                        is_italic=mutation_params.get("is_italic", False),
                        text_color=mutation_params.get("text_color", 0),
                    )

                    new_pdf_path = f"{user_id}/versions/{version_id}.pdf"
                    new_docx_path = f"{user_id}/versions/{version_id}.docx"

                    # Generate matching native DOCX for export consistency
                    doc_model = build_document_model(content, updated_geom or geometry_map)
                    docx_bytes = docx_compiler.compile(doc_model)

                    pdf_ok = _upload_to_storage(new_pdf_path, mutated_pdf, "application/pdf", jwt=jwt)
                    docx_ok = _upload_to_storage(new_docx_path, docx_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document", jwt=jwt)
                    if pdf_ok and docx_ok:
                        return {
                            "storage_path": new_pdf_path,
                            "docx_storage_path": new_docx_path,
                            "geometry": updated_geom,
                            "strategy": "direct_pdf_mutation",
                        }
                    logger.error(
                        "Direct mutation artifacts failed to upload (pdf_ok=%s docx_ok=%s); falling back to Document Compiler",
                        pdf_ok,
                        docx_ok,
                    )
            except Exception as e:
                logger.warning("Direct PDF mutation failed (%s); falling back to Document Compiler", e)

        # 2. Document Reconstruction / Compiler Pipeline (Pipeline B)
        doc_model = build_document_model(content, geometry_map)

        # Bounded fitting runs before persistence. It never drops below 10pt
        # body type and records every visible content/layout tradeoff.
        fit_result = fit_verifier.fit(
            doc_model,
            lambda model: pdf_compiler.compile(model)[0],
        )
        doc_model = fit_result.document
        docx_bytes = docx_compiler.compile(doc_model)
        pdf_bytes, ver_result = pdf_compiler.compile(doc_model, docx_bytes)

        # Extract precise physical geometry from verified PDF
        pdf_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        compiled_geometry = extract_document_geometry(pdf_doc).to_dict()
        pdf_doc.close()

        # Persist artifacts to storage; a success response must NEVER be returned
        # while the artifact itself is missing from storage.
        new_pdf_path = f"{user_id}/versions/{version_id}.pdf"
        new_docx_path = f"{user_id}/versions/{version_id}.docx"

        pdf_ok = _upload_to_storage(new_pdf_path, pdf_bytes, "application/pdf", jwt=jwt)
        docx_ok = _upload_to_storage(new_docx_path, docx_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document", jwt=jwt)
        if not (pdf_ok and docx_ok):
            raise RuntimeError(
                f"Failed to persist compiled artifacts to storage (pdf_ok={pdf_ok}, docx_ok={docx_ok})"
            )

        return {
            "storage_path": new_pdf_path,
            "docx_storage_path": new_docx_path,
            "geometry": compiled_geometry,
            "visual_verification": {
                "is_valid": ver_result.is_valid,
                "page_count": ver_result.page_count,
                "issues": [i.to_dict() for i in ver_result.issues],
            },
            "fit_verification": {
                "needs_manual_review": fit_result.needs_manual_review,
                "audit": fit_result.audit,
            },
            "strategy": "document_compiler",
        }


resume_compiler_service = ResumeCompilerService()
