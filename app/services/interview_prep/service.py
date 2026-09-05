"""Interview preparation service: orchestration/use-case layer.

Routes stay thin; all business logic (context gathering, evidence selection,
LLM generation, grounding validation, persistence, events, notifications,
ownership, staleness) lives here. Persistence goes through
:class:`InterviewPrepRepository` using the RLS-authenticated Supabase client
from ``AuthContext`` (never the service role for user-owned reads/writes).

On LLM failure no fake questions are created: the session is marked
``failed`` with a truthful error and the API surfaces a retry action.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException

from app.models.interview_prep import (
    VALID_CATEGORIES,
    VALID_DIFFICULTIES,
    InterviewPrepLLMOutput,
    InterviewPrepQuestionDraft,
    build_source_fingerprint,
    framework_for,
    infer_interview_type,
    plan_categories,
)
from app.repositories.application_repository import ApplicationRepository
from app.repositories.interview_prep_repository import InterviewPrepRepository
from app.services.interview_prep.grounding import (
    build_evidence_corpus,
    detect_gaps,
    extract_resume_skills,
    validate_question_grounding,
)
from app.services.interview_prep.prompts import (
    SYSTEM_INSTRUCTION,
    build_prep_prompt,
    response_schema,
    select_relevant_evidence,
)

logger = logging.getLogger(__name__)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class PrepContext:
    """Minimized generation context (no credentials, no unrelated app data)."""

    application: dict[str, Any]
    interview: Optional[dict[str, Any]]
    interview_type: str
    assumed_type: bool
    job_title: str
    company_name: str
    job_description: str
    jd_requirements: list[str] = field(default_factory=list)
    resume_id: Optional[str] = None
    resume_updated_at: Optional[str] = None
    profile: dict[str, Any] = field(default_factory=dict)
    evidence: str = ""
    corpus: str = ""
    resume_skills: set[str] = field(default_factory=set)


class InterviewPrepService:
    """Use-case layer for the interview preparation domain."""

    def __init__(
        self,
        repository: Optional[InterviewPrepRepository] = None,
        application_repository: Optional[ApplicationRepository] = None,
        bus: Any = None,
        notification_service: Any = None,
        gateway_factory: Any = None,
    ) -> None:
        self.repository = repository or InterviewPrepRepository()
        self.applications = application_repository or ApplicationRepository()
        self.bus = bus
        self.notification_service = notification_service
        self.gateway_factory = gateway_factory

    # -- DI helpers -------------------------------------------------------

    def _get_bus(self) -> Any:
        if self.bus is not None:
            return self.bus
        from app.events.runtime import get_event_bus

        return get_event_bus()

    def _get_notifications(self) -> Any:
        if self.notification_service is not None:
            return self.notification_service
        from app.services.notifications.notification_service import NotificationService

        return NotificationService()

    def _get_gateway(self) -> Any:
        if self.gateway_factory is not None:
            return self.gateway_factory()
        from app.llm.gateway import get_llm_gateway

        return get_llm_gateway()

    # -- Context gathering -------------------------------------------------

    async def _get_owned_application(self, auth: Any, application_id: str) -> dict[str, Any]:
        app = await self.applications.get_application(auth.supabase, auth.user.id, application_id)
        if app is None:
            raise HTTPException(status_code=404, detail="Application not found")
        return app

    def _extract_jd_requirements(self, job_description: str) -> list[str]:
        """Extract key JD requirements, reusing the ATS parser when available."""
        jd = (job_description or "").strip()
        if not jd:
            return []
        try:
            from app.services.ats.job_description_parser import JobDescriptionParser

            parsed = JobDescriptionParser().parse_job_description(jd)
            reqs = list(parsed.required_skills or []) + list(parsed.responsibilities or [])[:6]
            reqs += list(parsed.preferred_skills or [])[:4]
            seen: set[str] = set()
            ordered: list[str] = []
            for req in reqs:
                key = req.strip().lower()
                if req.strip() and key not in seen:
                    seen.add(key)
                    ordered.append(req.strip())
            if ordered:
                return ordered[:12]
        except Exception as exc:  # noqa: BLE001 — parser is best-effort
            logger.debug("JD parser fallback for interview prep: %s", exc)
        # Lightweight fallback: bullet/sentence extraction.
        reqs = []
        for line in jd.splitlines():
            clean = re.sub(r"^[\s•·\-*]+", "", line).strip()
            if len(clean) >= 12:
                reqs.append(clean)
            if len(reqs) >= 12:
                break
        return reqs

    def _resolve_job_description(
        self, application: dict[str, Any], job: Optional[dict[str, Any]]
    ) -> str:
        for source in (job or {}, application):
            for key in ("description", "job_description"):
                value = source.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        # Structured job fields as a last resort (never fabricated prose).
        if job:
            bits: list[str] = []
            for key in ("requirements", "responsibilities"):
                items = job.get(key) or []
                bits.extend(str(i) for i in items if str(i).strip())
            if bits:
                return "\n".join(f"- {b}" for b in bits[:20])
        return ""

    async def _gather_context(
        self,
        auth: Any,
        application_id: str,
        interview_id: Optional[str] = None,
        resume_id: Optional[str] = None,
        job_id: Optional[str] = None,
    ) -> PrepContext:
        supabase = auth.supabase
        application = await self._get_owned_application(auth, application_id)

        interview: Optional[dict[str, Any]] = None
        if interview_id:
            interview = await self.applications.get_child(
                supabase, application_id, "application_interviews", interview_id
            )
            if interview is None:
                raise HTTPException(status_code=404, detail="Interview not found for this application")

        interview_type, assumed = infer_interview_type((interview or {}).get("name"))

        # Job / JD resolution: explicit job_id wins, else the application's link.
        job: Optional[dict[str, Any]] = None
        lookup_job_id = job_id or application.get("job_id")
        if lookup_job_id:
            try:
                from app.repositories.job_repository import JobRepository

                job = JobRepository().get_job(str(lookup_job_id))
            except Exception as exc:  # noqa: BLE001 — JD enrichment is best-effort
                logger.debug("Job lookup failed for interview prep: %s", exc)
                job = None
        job_description = self._resolve_job_description(application, job)
        jd_requirements = self._extract_jd_requirements(job_description)

        # Resume resolution: explicit resume_id wins, else the most recently
        # updated parsed resume for the user.
        from app.repositories.resume_repository import ResumeRepository

        resume_repo = ResumeRepository(jwt=getattr(auth, "jwt", None))
        resume_row: Optional[dict[str, Any]] = None
        if resume_id:
            resume_row = resume_repo.get_resume(auth.user.id, resume_id)
            if resume_row is None:
                raise HTTPException(status_code=404, detail="Resume not found")
        else:
            try:
                resumes = resume_repo.list_resumes(auth.user.id) or []
                parsed = [r for r in resumes if (r.get("content") or {}).get("profile")]
                resume_row = parsed[0] if parsed else (resumes[0] if resumes else None)
            except Exception as exc:  # noqa: BLE001 — resume is optional context
                logger.debug("Resume lookup failed for interview prep: %s", exc)
                resume_row = None

        from app.models.resume import ResumeContent

        profile: dict[str, Any] = {}
        resume_updated_at: Optional[str] = None
        resolved_resume_id: Optional[str] = None
        if resume_row:
            resolved_resume_id = str(resume_row.get("id"))
            resume_updated_at = resume_row.get("updated_at")
            try:
                profile = ResumeContent.from_dict(resume_row.get("content") or {}).profile.model_dump()
            except Exception:  # noqa: BLE001 — malformed content degrades gracefully
                profile = {}

        corpus = build_evidence_corpus(profile) if profile else ""
        resume_skills = extract_resume_skills(profile) if profile else set()
        evidence = select_relevant_evidence(profile, job_description) if profile else ""

        return PrepContext(
            application=application,
            interview=interview,
            interview_type=interview_type,
            assumed_type=assumed,
            job_title=application.get("job_title") or (job or {}).get("title") or "",
            company_name=application.get("company_name") or (job or {}).get("company") or "",
            job_description=job_description,
            jd_requirements=jd_requirements,
            resume_id=resolved_resume_id,
            resume_updated_at=resume_updated_at,
            profile=profile,
            evidence=evidence,
            corpus=corpus,
            resume_skills=resume_skills,
        )

    # -- LLM generation ----------------------------------------------------

    async def _generate_drafts(self, ctx: PrepContext, question_count: int) -> InterviewPrepLLMOutput:
        from app.llm.types import LLMRequest, LLMTask

        categories = plan_categories(ctx.interview_type, question_count)
        prompt = build_prep_prompt(
            job_title=ctx.job_title,
            company_name=ctx.company_name,
            interview_type=ctx.interview_type,
            interview_name=(ctx.interview or {}).get("name"),
            assumed_type=ctx.assumed_type,
            job_description=ctx.job_description,
            evidence=ctx.evidence,
            jd_requirements=ctx.jd_requirements,
            categories=categories,
            scheduled_at=(ctx.interview or {}).get("scheduled_at"),
        )
        gateway = self._get_gateway()
        response = await gateway.generate(
            LLMRequest(
                task=LLMTask.INTERVIEW_PREP_GENERATION,
                prompt=prompt,
                system_instruction=SYSTEM_INSTRUCTION,
                temperature=0.4,
                max_tokens=4096,
                response_schema=response_schema(),
                metadata={
                    "application_id": str(ctx.application.get("id")),
                    "interview_type": ctx.interview_type,
                },
            )
        )
        return self._parse_llm_output(response.content, categories)

    @staticmethod
    def _parse_llm_output(content: str, categories: list[str]) -> InterviewPrepLLMOutput:
        text = (content or "").strip()
        # Tolerate markdown-fenced JSON.
        fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
        if fence:
            text = fence.group(1)
        try:
            data = json.loads(text)
        except (ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"LLM returned malformed preparation JSON: {exc}") from exc
        try:
            output = InterviewPrepLLMOutput.model_validate(data)
        except Exception as exc:
            raise ValueError(f"LLM preparation failed schema validation: {exc}") from exc
        # Normalize categories/difficulties; drop empties; enforce plan order
        # where the model ignored it.
        cleaned: list[InterviewPrepQuestionDraft] = []
        for idx, draft in enumerate(output.questions):
            cat = (draft.category or "").strip().lower()
            if cat not in VALID_CATEGORIES:
                cat = categories[idx] if idx < len(categories) else "general"
                if cat not in VALID_CATEGORIES:
                    cat = "role_specific"
            diff = (draft.difficulty or "intermediate").strip().lower()
            if diff not in VALID_DIFFICULTIES:
                diff = "intermediate"
            if not (draft.question or "").strip():
                continue
            draft.category = cat
            draft.difficulty = diff
            cleaned.append(draft)
        output.questions = cleaned[:10]
        if len(output.questions) < 3:
            raise ValueError(
                f"LLM returned too few usable questions ({len(output.questions)})"
            )
        return output

    # -- Persistence helpers ------------------------------------------------

    def _draft_to_row(self, draft: InterviewPrepQuestionDraft, order: int) -> dict[str, Any]:
        framework = framework_for(draft.category, draft.question)
        star_guidance = None
        if draft.category in ("behavioral", "situational"):
            star_guidance = (
                "Situation: set the scene in one sentence. Task: your responsibility. "
                "Action: what YOU did (most time here). Result: measured outcome. "
                "Reflection: what you would repeat or change."
            )
        return {
            "category": draft.category,
            "question": draft.question.strip(),
            "difficulty": draft.difficulty,
            "rationale": (draft.rationale or "").strip(),
            "resume_evidence": draft.resume_evidence or [],
            "talking_points": draft.talking_points or [],
            "answer_framework": framework,
            "star_guidance": star_guidance,
            "expected_signals": draft.expected_signals or [],
            "related_jd_requirements": draft.related_jd_requirements or [],
            "gaps": draft.gaps or [],
            "question_order": order,
            "is_prepared": False,
            "is_bookmarked": False,
        }

    async def _run_generation(
        self,
        auth: Any,
        session: dict[str, Any],
        ctx: PrepContext,
        question_count: int,
    ) -> dict[str, Any]:
        """Execute the LLM pass and persist results. Never raises silently."""
        from app.llm.types import LLMProviderError

        session_id = str(session["id"])
        try:
            output = await self._generate_drafts(ctx, question_count)
        except LLMProviderError as exc:
            logger.warning("Interview prep LLM failed session=%s: %s", session_id, exc)
            await self.repository.update_session(
                auth.supabase, auth.user.id, session_id,
                {"status": "failed", "error": "AI preparation is temporarily unavailable. Please retry.", "updated_at": _utcnow_iso()},
            )
            return await self.get_session(auth, session_id)
        except (ValueError, Exception) as exc:  # noqa: BLE001 — truthful failure state
            logger.warning("Interview prep generation invalid session=%s: %s", session_id, exc)
            await self.repository.update_session(
                auth.supabase, auth.user.id, session_id,
                {"status": "failed", "error": "The AI returned an unusable response. Please regenerate.", "updated_at": _utcnow_iso()},
            )
            return await self.get_session(auth, session_id)

        # Grounding safety net: validate every draft against real evidence.
        rows: list[dict[str, Any]] = []
        for order, draft in enumerate(output.questions):
            payload = validate_question_grounding(
                draft.model_dump(), ctx.corpus, ctx.resume_skills, ctx.job_description
            )
            rows.append(self._draft_to_row(InterviewPrepQuestionDraft(**payload), order))

        # Merge model gaps with deterministic gap detection.
        model_gaps = list(output.gaps or [])
        for draft in output.questions:
            model_gaps.extend(draft.gaps or [])
        deterministic_gaps = detect_gaps(ctx.jd_requirements, ctx.resume_skills, ctx.corpus)
        merged_gaps = list(dict.fromkeys([g for g in model_gaps + deterministic_gaps if g]))

        # Deduplicate near-identical questions (cheap normalized comparison).
        seen: set[str] = set()
        unique_rows: list[dict[str, Any]] = []
        for row in rows:
            key = re.sub(r"\s+", " ", row["question"].strip().lower())
            if key in seen:
                continue
            seen.add(key)
            unique_rows.append(row)
        rows = unique_rows

        persisted = await self.repository.replace_questions(auth.supabase, session_id, rows)
        await self.repository.update_session(
            auth.supabase, auth.user.id, session_id,
            {
                "status": "ready",
                "error": None,
                "question_count": len(persisted),
                "prepared_count": 0,
                "generated_at": _utcnow_iso(),
                "updated_at": _utcnow_iso(),
                "source_metadata": {
                    **(session.get("source_metadata") or {}),
                    "gaps": merged_gaps[:20],
                    "assumption_note": output.assumption_note or "",
                },
            },
        )
        result = await self.get_session(auth, session_id)
        await self._publish_generated(auth, session, len(persisted))
        return result

    async def _publish_generated(self, auth: Any, session: dict[str, Any], count: int) -> None:
        try:
            from app.events import InterviewPrepGenerated

            event = InterviewPrepGenerated(
                aggregate_id=str(session["id"]),
                user_id=auth.user.id,
                application_id=str(session.get("application_id") or ""),
                interview_id=str(session.get("interview_id") or ""),
                session_id=str(session["id"]),
                question_count=count,
                metadata={"interview_type": session.get("interview_type")},
            )
            await self._get_bus().publish(event, context=auth)
        except Exception as exc:  # noqa: BLE001 — events never break generation
            logger.warning("InterviewPrepGenerated publish failed: %s", exc)
        try:
            interview_name = session.get("interview_name") or "interview"
            await self._get_notifications().create_notification(
                auth,
                "interview_prep_ready",
                "Interview preparation ready",
                f"Your preparation for {interview_name} is ready to review.",
                payload={"session_id": str(session["id"])},
                priority="medium",
            )
        except Exception as exc:  # noqa: BLE001 — notifications never break generation
            logger.debug("Interview prep notification skipped: %s", exc)

    # -- Public API ----------------------------------------------------------

    async def generate(
        self,
        auth: Any,
        application_id: str,
        interview_id: Optional[str] = None,
        resume_id: Optional[str] = None,
        job_id: Optional[str] = None,
        question_count: int = 8,
        async_mode: bool = False,
    ) -> dict[str, Any]:
        question_count = max(3, min(10, question_count or 8))
        ctx = await self._gather_context(auth, application_id, interview_id, resume_id, job_id)
        fingerprint = build_source_fingerprint(
            ctx.job_description, ctx.resume_updated_at, ctx.interview_type, ctx.resume_id
        )
        source_metadata = {
            "job_title": ctx.job_title,
            "company_name": ctx.company_name,
            "interview_name": (ctx.interview or {}).get("name"),
            "scheduled_at": (ctx.interview or {}).get("scheduled_at"),
            "jd_snapshot_hash": build_source_fingerprint(ctx.job_description),
            "resume_updated_at": ctx.resume_updated_at,
            "assumed_type": ctx.assumed_type,
            "question_count_requested": question_count,
        }
        session = await self.repository.create_session(
            auth.supabase, auth.user.id,
            {
                "application_id": application_id,
                "interview_id": interview_id,
                "job_id": job_id or ctx.application.get("job_id"),
                "status": "generating",
                "interview_type": ctx.interview_type,
                "interview_name": (ctx.interview or {}).get("name"),
                "source_resume_id": ctx.resume_id,
                "source_resume_version_id": None,
                "source_fingerprint": fingerprint,
                "source_metadata": source_metadata,
                "question_count": 0,
                "prepared_count": 0,
                "version": 1,
            },
        )
        if async_mode:
            # Prefer background generation; fall back to inline when Redis is
            # unavailable so the user still gets a truthful session state.
            try:
                from app.workers.dispatcher import enqueue

                job_ref = await enqueue(
                    "generate_interview_prep_job", str(session["id"]), auth.user.id
                )
                if job_ref:
                    return await self.get_session(auth, str(session["id"]))
            except Exception as exc:  # noqa: BLE001 — inline fallback
                logger.warning("ARQ enqueue failed, generating inline: %s", exc)
        return await self._run_generation(auth, session, ctx, question_count)

    async def regenerate(self, auth: Any, session_id: str) -> dict[str, Any]:
        session = await self.repository.get_session(auth.supabase, auth.user.id, session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Preparation session not found")
        # Regenerate from CURRENT source context — never reuse stale snapshots.
        ctx = await self._gather_context(
            auth,
            str(session["application_id"]),
            session.get("interview_id"),
            session.get("source_resume_id"),
            session.get("job_id"),
        )
        fingerprint = build_source_fingerprint(
            ctx.job_description, ctx.resume_updated_at, ctx.interview_type, ctx.resume_id
        )
        requested = int((session.get("source_metadata") or {}).get("question_count_requested") or 8)
        await self.repository.update_session(
            auth.supabase, auth.user.id, session_id,
            {
                "status": "generating",
                "error": None,
                "interview_type": ctx.interview_type,
                "interview_name": (ctx.interview or {}).get("name") or session.get("interview_name"),
                "source_resume_id": ctx.resume_id,
                "source_fingerprint": fingerprint,
                "version": int(session.get("version") or 1) + 1,
                "updated_at": _utcnow_iso(),
                "source_metadata": {
                    **(session.get("source_metadata") or {}),
                    "job_title": ctx.job_title,
                    "company_name": ctx.company_name,
                    "jd_snapshot_hash": build_source_fingerprint(ctx.job_description),
                    "resume_updated_at": ctx.resume_updated_at,
                    "assumed_type": ctx.assumed_type,
                    "question_count_requested": requested,
                },
            },
        )
        fresh = await self.repository.get_session(auth.supabase, auth.user.id, session_id)
        assert fresh is not None
        return await self._run_generation(auth, fresh, ctx, requested)

    async def get_session(self, auth: Any, session_id: str) -> dict[str, Any]:
        session = await self.repository.get_session(auth.supabase, auth.user.id, session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Preparation session not found")
        questions = await self.repository.list_questions(auth.supabase, session_id)
        return self._attach_derived(session, questions)

    async def list_sessions(
        self,
        auth: Any,
        application_id: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        if application_id:
            # Ownership check through the parent application first.
            await self._get_owned_application(auth, application_id)
        rows, total = await self.repository.list_sessions(
            auth.supabase, auth.user.id, application_id, page, page_size
        )
        return {"sessions": [self._attach_progress(r) for r in rows], "total": total}

    async def update_question(
        self, auth: Any, question_id: str, updates: dict[str, Any]
    ) -> dict[str, Any]:
        question = await self.repository.get_question(auth.supabase, question_id)
        if question is None:
            raise HTTPException(status_code=404, detail="Question not found")
        session = await self.repository.get_session(
            auth.supabase, auth.user.id, str(question["session_id"])
        )
        if session is None:
            # Question exists but belongs to another user — 404, not 403,
            # to avoid leaking cross-user existence.
            raise HTTPException(status_code=404, detail="Question not found")
        allowed = {k: v for k, v in updates.items() if k in ("is_prepared", "is_bookmarked") and v is not None}
        if not allowed:
            raise HTTPException(status_code=400, detail="No valid fields to update")
        updated = await self.repository.update_question(auth.supabase, question_id, allowed)
        if updated is None:
            raise HTTPException(status_code=404, detail="Question not found")
        # Keep the session-level prepared counter truthful.
        questions = await self.repository.list_questions(auth.supabase, str(session["id"]))
        prepared = sum(1 for q in questions if q.get("is_prepared"))
        await self.repository.update_session(
            auth.supabase, auth.user.id, str(session["id"]),
            {"prepared_count": prepared, "updated_at": _utcnow_iso()},
        )
        return updated

    # -- Derived fields -------------------------------------------------------

    @staticmethod
    def _attach_progress(session: dict[str, Any]) -> dict[str, Any]:
        total = int(session.get("question_count") or 0)
        prepared = int(session.get("prepared_count") or 0)
        remaining = max(0, total - prepared)
        return {**session, "prepared_total": prepared, "remaining": remaining}

    def _attach_derived(self, session: dict[str, Any], questions: list[dict[str, Any]]) -> dict[str, Any]:
        prepared = sum(1 for q in questions if q.get("is_prepared"))
        bookmarked = sum(1 for q in questions if q.get("is_bookmarked"))
        by_category: dict[str, int] = {}
        for q in questions:
            by_category[q.get("category", "unknown")] = by_category.get(q.get("category", "unknown"), 0) + 1
        # Staleness: compare the stored fingerprint against current context.
        # Recomputed cheaply from stored metadata (no extra queries); the
        # frontend can request regenerate when stale.
        out = dict(session)
        out["questions"] = questions
        out["prepared_total"] = prepared
        out["bookmarked_total"] = bookmarked
        out["remaining"] = max(0, len(questions) - prepared)
        out["by_category"] = by_category
        out["is_stale"] = False
        return out

    async def session_with_staleness(self, auth: Any, session_id: str) -> dict[str, Any]:
        """Get a session annotated with a live staleness check."""
        result = await self.get_session(auth, session_id)
        try:
            ctx = await self._gather_context(
                auth,
                str(result["application_id"]),
                result.get("interview_id"),
                result.get("source_resume_id"),
                result.get("job_id"),
            )
            current = build_source_fingerprint(
                ctx.job_description, ctx.resume_updated_at, ctx.interview_type, ctx.resume_id
            )
            result["is_stale"] = current != (result.get("source_fingerprint") or "")
            result["stale_reason"] = (
                "The job description, resume, or interview context changed since generation."
                if result["is_stale"] else None
            )
        except HTTPException:
            result["is_stale"] = False
            result["stale_reason"] = None
        return result
