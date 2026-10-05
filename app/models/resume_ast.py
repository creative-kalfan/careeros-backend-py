from pydantic import BaseModel, Field
from typing import List, Optional, Any, Dict
from uuid import UUID, uuid4

class ASTNode(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    type: str

class SkillNode(ASTNode):
    type: str = "skill"
    name: str
    level: Optional[str] = None

class ExperienceNode(ASTNode):
    type: str = "experience"
    company: str
    role: str
    description: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    bullets: List[str] = Field(default_factory=list)

class ProfileNode(ASTNode):
    type: str = "profile"
    name: Optional[str] = None
    email: Optional[str] = None
    summary: Optional[str] = None

class ResumeNode(ASTNode):
    type: str = "resume"
    profile: Optional[ProfileNode] = None
    experiences: List[ExperienceNode] = Field(default_factory=list)
    skills: List[SkillNode] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
