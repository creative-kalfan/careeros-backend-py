"""ATS Router endpoints for CareerOS Resume Module (Step 4)."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Header, status

from app.dependencies import get_current_user
from app.auth.service import AuthContext
from app.models.ats import ATSAnalysisReport
from app.models.resume import ResumeContent
from app.schemas.ats import (
    AnalyzeResumeRequest,
    AnalyzeResumeResponse,
    ATSAnalysisReportResponse,
    ListATSReportsResponse
)
from app.services.ats.ats_analyzer import ATSAnalyzer
from app.repositories.ats_repository import ATSReportRepository
from app.repositories.resume_repository import ResumeRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ats", tags=["ats"])

# Reuse existing resume repository
resume_repo = ResumeRepository()
ats_repo = ATSReportRepository()
analyzer = ATSAnalyzer()

def get_auth_token(authorization: Optional[str] = Header(None)) -> Optional[str]:
    """Helper to extract access token from Authorization header."""
    if not authorization:
        return None
    try:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1]
    except Exception:
        pass
    return None

@router.post("/analyze", response_model=AnalyzeResumeResponse)
async def analyze_resume(
    payload: AnalyzeResumeRequest,
    current_user: AuthContext = Depends(get_current_user),
    token: Optional[str] = Depends(get_auth_token)
) -> AnalyzeResumeResponse:
    """Analyze a candidate's resume against a job description."""
    try:
        if not payload.job_description or not payload.job_description.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Job description cannot be empty"
            )

        jwt_token = current_user.jwt or token
        repo = ResumeRepository(jwt=jwt_token)
        owned_resume = repo.get_resume(current_user.user.id, payload.resume_id)
        if not owned_resume:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Resume not found or unauthorized access"
            )

        version_id = payload.version_id
        if version_id:
            version = repo.get_version(version_id)
            if not version:
                raise HTTPException(status_code=404, detail="Version not found")
            if version.get("resume_id") != payload.resume_id:
                raise HTTPException(status_code=400, detail="Version does not belong to this resume")
            resume_content = ResumeContent.from_dict(version.get("content") or {})
        else:
            resume_content = ResumeContent.from_dict(owned_resume.get("content"))

        # 2. Run ATS Analysis
        analysis_result = analyzer.analyze_resume(
            resume_content=resume_content,
            job_description=payload.job_description,
            job_title=payload.job_title,
            company=payload.company
        )

        report_id = None
        # 3. Persist analysis report optionally
        if payload.persist:
            report_id = str(uuid.uuid4())
            parsed_job = analyzer.parser.parse_job_description(
                payload.job_description, payload.job_title, payload.company
            )
            
            report = ATSAnalysisReport(
                id=report_id,
                resume_id=payload.resume_id,
                version_id=version_id,
                job_title=payload.job_title,
                company=payload.company,
                job_description=payload.job_description,
                parsed_job_data=parsed_job.model_dump(mode="json"),
                overall_score=analysis_result.overall_score,
                keyword_match_score=analysis_result.keyword_match_score,
                skills_match_score=analysis_result.skills_match_score,
                experience_relevance_score=analysis_result.experience_relevance_score,
                qualification_match_score=analysis_result.qualification_match_score,
                structure_format_score=analysis_result.structure_format_score,
                matched_keywords=analysis_result.matched_keywords,
                missing_keywords=analysis_result.missing_keywords,
                partial_keywords=analysis_result.partial_keywords,
                matched_skills=analysis_result.matched_skills,
                missing_skills=analysis_result.missing_skills,
                partial_skills=analysis_result.partial_skills,
                requirement_analysis=[req.model_dump(mode="json") for req in analysis_result.requirement_coverage],
                recommendations=analysis_result.recommendations,
                high_priority_recommendations=analysis_result.high_priority_recommendations,
                medium_priority_recommendations=analysis_result.medium_priority_recommendations,
                low_priority_recommendations=analysis_result.low_priority_recommendations,
                template_analysis=analysis_result.template_analysis,
                section_analysis=analysis_result.section_analysis,
                analysis_explanation=analysis_result.analysis_explanation,
                scoring_version=analysis_result.scoring_version,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            
            ats_repo.create_report(report, jwt=jwt_token)
            if version_id:
                repo.update_version(version_id, {
                    "last_ats_score": analysis_result.overall_score,
                    "last_analyzed_at": datetime.utcnow().isoformat(),
                })

        return AnalyzeResumeResponse(
            result=analysis_result,
            report_id=report_id,
            message="Resume analyzed successfully against target job"
        )

    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error("Error during ATS resume analysis: %s", str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="ATS analysis failed",
        )

@router.get("/reports/{report_id}", response_model=ATSAnalysisReportResponse)
async def get_ats_report(
    report_id: str,
    current_user: AuthContext = Depends(get_current_user),
    token: Optional[str] = Depends(get_auth_token)
) -> ATSAnalysisReportResponse:
    """Retrieve a specific ATS Analysis report by report_id."""
    jwt_token = current_user.jwt or token
    report = ats_repo.get_report(report_id, jwt=jwt_token)
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Report not found or unauthorized access"
        )

    # Explicit application-level ownership check (defense in depth)
    repo = ResumeRepository(jwt=jwt_token)
    if report.resume_id:
        resume = repo.get_resume(current_user.user.id, report.resume_id)
        if not resume:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Report not found or unauthorized access"
            )
    
    return ATSAnalysisReportResponse(
        id=report.id,
        resume_id=report.resume_id,
        version_id=report.version_id,
        job_title=report.job_title,
        company=report.company,
        overall_score=report.overall_score,
        keyword_match_score=report.keyword_match_score,
        skills_match_score=report.skills_match_score,
        experience_relevance_score=report.experience_relevance_score,
        qualification_match_score=report.qualification_match_score,
        structure_format_score=report.structure_format_score,
        created_at=report.created_at,
        updated_at=report.updated_at
    )

@router.get("/resume/{resume_id}/history", response_model=ListATSReportsResponse)
async def list_ats_history(
    resume_id: str,
    current_user: AuthContext = Depends(get_current_user),
    token: Optional[str] = Depends(get_auth_token)
) -> ListATSReportsResponse:
    """List historical reports for a given resume."""
    jwt_token = current_user.jwt or token
    repo = ResumeRepository(jwt=jwt_token)
    resume = repo.get_resume(current_user.user.id, resume_id)
    if not resume:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Resume not found or unauthorized access"
        )
    reports = ats_repo.list_reports_for_resume(resume_id, jwt=jwt_token)
    
    report_responses = [
        ATSAnalysisReportResponse(
            id=r.id,
            resume_id=r.resume_id,
            version_id=r.version_id,
            job_title=r.job_title,
            company=r.company,
            overall_score=r.overall_score,
            keyword_match_score=r.keyword_match_score,
            skills_match_score=r.skills_match_score,
            experience_relevance_score=r.experience_relevance_score,
            qualification_match_score=r.qualification_match_score,
            structure_format_score=r.structure_format_score,
            created_at=r.created_at,
            updated_at=r.updated_at
        )
        for r in reports
    ]
    
    return ListATSReportsResponse(reports=report_responses)
