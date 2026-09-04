"""ATS Analysis Repository for CareerOS (Step 4)."""

from __future__ import annotations

from typing import List, Dict, Any, Optional
from datetime import datetime
import logging

from app.models.ats import ATSAnalysisReport
from app.db.supabase import get_service_client, get_authenticated_client

logger = logging.getLogger(__name__)

class ATSReportRepository:
    """Repository managing the persistence of ATS analysis reports in Supabase."""

    def __init__(self, supabase_client=None):
        self._client = supabase_client

    def _get_client(self, jwt: Optional[str] = None):
        """Get authenticated or anonymous Supabase client."""
        if self._client:
            return self._client
        if jwt:
            return get_authenticated_client(jwt)
        return get_service_client()

    def create_report(self, report: ATSAnalysisReport, jwt: Optional[str] = None) -> ATSAnalysisReport:
        """Create a persistent ATS report record in resume_ats_analyses table."""
        client = self._get_client(jwt)
        data = {
            "id": report.id,
            "resume_id": report.resume_id,
            "version_id": report.version_id,
            "job_title": report.job_title,
            "company": report.company,
            "job_description": report.job_description,
            "parsed_job_data": report.parsed_job_data,
            "overall_score": report.overall_score,
            "keyword_match_score": report.keyword_match_score,
            "skills_match_score": report.skills_match_score,
            "experience_relevance_score": report.experience_relevance_score,
            "qualification_match_score": report.qualification_match_score,
            "structure_format_score": report.structure_format_score,
            "matched_keywords": report.matched_keywords,
            "missing_keywords": report.missing_keywords,
            "partial_keywords": report.partial_keywords,
            "matched_skills": report.matched_skills,
            "missing_skills": report.missing_skills,
            "partial_skills": report.partial_skills,
            "requirement_analysis": report.requirement_analysis,
            "recommendations": report.recommendations,
            "high_priority_recommendations": report.high_priority_recommendations,
            "medium_priority_recommendations": report.medium_priority_recommendations,
            "low_priority_recommendations": report.low_priority_recommendations,
            "template_analysis": report.template_analysis,
            "section_analysis": report.section_analysis,
            "analysis_explanation": report.analysis_explanation,
            "scoring_version": report.scoring_version,
            "created_at": report.created_at.isoformat(),
            "updated_at": report.updated_at.isoformat()
        }

        # Perform the insert. Supabase RLS will validate if user owns the resume
        result = client.table("resume_ats_analyses").insert(data).execute()
        if not result.data:
            raise RuntimeError("Failed to persist ATS analysis report")
        return report

    def get_report(self, report_id: str, jwt: Optional[str] = None) -> Optional[ATSAnalysisReport]:
        """Fetch a specific ATS analysis report by ID."""
        client = self._get_client(jwt)
        result = client.table("resume_ats_analyses").select("*").eq("id", report_id).execute()
        if not result.data:
            return None
        
        row = result.data[0]
        return ATSAnalysisReport(
            id=row["id"],
            resume_id=row["resume_id"],
            version_id=row.get("version_id"),
            job_title=row.get("job_title"),
            company=row.get("company"),
            job_description=row["job_description"],
            parsed_job_data=row["parsed_job_data"],
            overall_score=row["overall_score"],
            keyword_match_score=row["keyword_match_score"],
            skills_match_score=row["skills_match_score"],
            experience_relevance_score=row["experience_relevance_score"],
            qualification_match_score=row["qualification_match_score"],
            structure_format_score=row["structure_format_score"],
            matched_keywords=row["matched_keywords"],
            missing_keywords=row["missing_keywords"],
            partial_keywords=row["partial_keywords"],
            matched_skills=row["matched_skills"],
            missing_skills=row["missing_skills"],
            partial_skills=row["partial_skills"],
            requirement_analysis=row["requirement_analysis"],
            recommendations=row["recommendations"],
            high_priority_recommendations=row.get("high_priority_recommendations") or [],
            medium_priority_recommendations=row.get("medium_priority_recommendations") or [],
            low_priority_recommendations=row.get("low_priority_recommendations") or [],
            template_analysis=row["template_analysis"],
            section_analysis=row["section_analysis"],
            analysis_explanation=row["analysis_explanation"],
            scoring_version=row["scoring_version"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"])
        )

    def list_reports_for_resume(self, resume_id: str, jwt: Optional[str] = None) -> List[ATSAnalysisReport]:
        """List historical reports generated for a given resume."""
        client = self._get_client(jwt)
        result = client.table("resume_ats_analyses").select("*").eq("resume_id", resume_id).order("created_at", desc=True).execute()
        
        reports = []
        for row in result.data:
            reports.append(ATSAnalysisReport(
                id=row["id"],
                resume_id=row["resume_id"],
                version_id=row.get("version_id"),
                job_title=row.get("job_title"),
                company=row.get("company"),
                job_description=row["job_description"],
                parsed_job_data=row["parsed_job_data"],
                overall_score=row["overall_score"],
                keyword_match_score=row["keyword_match_score"],
                skills_match_score=row["skills_match_score"],
                experience_relevance_score=row["experience_relevance_score"],
                qualification_match_score=row["qualification_match_score"],
                structure_format_score=row["structure_format_score"],
                matched_keywords=row["matched_keywords"],
                missing_keywords=row["missing_keywords"],
                partial_keywords=row["partial_keywords"],
                matched_skills=row["matched_skills"],
                missing_skills=row["missing_skills"],
                partial_skills=row["partial_skills"],
                requirement_analysis=row["requirement_analysis"],
                recommendations=row["recommendations"],
                high_priority_recommendations=row.get("high_priority_recommendations") or [],
                medium_priority_recommendations=row.get("medium_priority_recommendations") or [],
                low_priority_recommendations=row.get("low_priority_recommendations") or [],
                template_analysis=row["template_analysis"],
                section_analysis=row["section_analysis"],
                analysis_explanation=row["analysis_explanation"],
                scoring_version=row["scoring_version"],
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"])
            ))
        return reports
