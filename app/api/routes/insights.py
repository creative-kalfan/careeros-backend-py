from typing import Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.dependencies import get_current_user
from app.auth.service import AuthContext
from app.schemas.common import SuccessResponse
from app.repositories.resume_repository import ResumeRepository
from app.models.resume import ResumeContent

router = APIRouter(prefix="/api/insights", tags=["insights"])

@router.get("/skill-gap", response_model=SuccessResponse[dict])
async def get_skill_gap(
    resume_id: str | None = None,
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[dict]:
    """Compare user's AST skills vs top 10 market trends for their role."""
    resume_repo = ResumeRepository(auth.supabase)
    resume = None
    if resume_id:
        resume = resume_repo.get_resume(auth.user.id, resume_id)
    else:
        # Get most recent resume
        resumes = resume_repo.list_resumes(auth.user.id, page=1, page_size=1)
        if resumes.data:
            resume = resume_repo.get_resume(auth.user.id, resumes.data[0].get("id"))
            
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")
        
    try:
        resume_content = ResumeContent.model_validate(resume.get("content") or {})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid resume content")
        
    # Get user skills
    user_skills = []
    if resume_content.profile and resume_content.profile.skills:
        skills_obj = resume_content.profile.skills
        for s_list in (skills_obj.technical, skills_obj.tools, skills_obj.languages, skills_obj.databases, skills_obj.analytics, skills_obj.soft_skills):
            user_skills.extend(s_list or [])
        if skills_obj.custom:
            for c_list in skills_obj.custom.values():
                user_skills.extend(c_list or [])
    
    user_skills_lower = {s.lower() for s in user_skills}
    
    # Determine user role from resume or default to General
    role_title = resume.get("target_job_title") or resume_content.profile.personal.headline or "General"
    
    # Try to find exact match in market_skill_trends or fallback to General
    res = auth.supabase.table("market_skill_trends").select("*").eq("role_title", role_title).order("frequency", desc=True).limit(10).execute()
    trends = res.data or []
    
    if not trends:
        # Fallback to General
        res = auth.supabase.table("market_skill_trends").select("*").eq("role_title", "General").order("frequency", desc=True).limit(10).execute()
        trends = res.data or []
        
    missing_skills = []
    matched_skills = []
    
    for t in trends:
        skill_name = t.get("skill_name")
        if skill_name.lower() in user_skills_lower:
            matched_skills.append(skill_name)
        else:
            missing_skills.append(skill_name)
            
    total = len(trends)
    match_percent = int((len(matched_skills) / total) * 100) if total > 0 else 100
    
    return SuccessResponse(data={
        "match_percent": match_percent,
        "matched_skills": matched_skills,
        "missing_skills": missing_skills,
        "market_trends": trends
    })
