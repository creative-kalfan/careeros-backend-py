"""Skills parsing."""

from __future__ import annotations

import re
from typing import List, Set

from .models import DocumentBlock
from .text_utils import split_skills_line, is_bullet_line, strip_bullet


# Common skill categories for classification
SKILL_CATEGORIES = {
    "programming": {
        "python", "java", "javascript", "typescript", "c++", "c#", "c", "go", "rust",
        "ruby", "php", "swift", "kotlin", "scala", "r", "matlab", "perl", "shell",
        "bash", "powershell", "sql", "nosql", "html", "css", "scss", "sass",
    },
    "frameworks": {
        "react", "angular", "vue", "svelte", "next.js", "nuxt", "django", "flask",
        "fastapi", "spring", "spring boot", "express", "nestjs", "laravel", "rails",
        "asp.net", ".net", "node.js", "nodejs", "deno", "bun",
    },
    "cloud": {
        "aws", "azure", "gcp", "google cloud", "cloud", "ec2", "s3", "lambda",
        "rds", "dynamodb", "cloudformation", "terraform", "pulumi",
    },
    "devops": {
        "docker", "kubernetes", "k8s", "helm", "jenkins", "gitlab ci", "github actions",
        "ci/cd", "cicd", "ansible", "chef", "puppet", "vagrant", "prometheus",
        "grafana", "elk", "datadog", "new relic", "splunk",
    },
    "databases": {
        "postgresql", "postgres", "mysql", "mongodb", "redis", "elasticsearch",
        "cassandra", "oracle", "sql server", "sqlite", "dynamodb", "firestore",
        "mariadb", "couchdb", "neo4j", "influxdb", "timescaledb",
    },
    "data": {
        "pandas", "numpy", "scipy", "matplotlib", "seaborn", "plotly", "tableau",
        "power bi", "looker", "metabase", "superset", "spark", "hadoop", "kafka",
        "airflow", "dbt", "snowflake", "bigquery", "redshift", "databricks",
    },
    "ml_ai": {
        "tensorflow", "pytorch", "keras", "scikit-learn", "sklearn", "xgboost",
        "lightgbm", "catboost", "hugging face", "transformers", "bert", "gpt",
        "llm", "nlp", "computer vision", "opencv", "mlflow", "wandb",
    },
    "tools": {
        "git", "github", "gitlab", "bitbucket", "jira", "confluence", "trello",
        "notion", "slack", "teams", "figma", "sketch", "adobe", "photoshop",
        "illustrator", "postman", "swagger", "insomnia", "curl", "vs code",
        "intellij", "pycharm", "vim", "emacs", "docker compose",
    },
    "languages": {
        "english", "spanish", "french", "german", "mandarin", "chinese", "japanese",
        "korean", "hindi", "tamil", "telugu", "bengali", "portuguese", "italian",
        "russian", "arabic", "fluent", "native", "proficient", "conversational",
    },
}


def classify_skill(skill: str) -> str:
    """Classify a skill into a category."""
    lower = skill.lower().strip()
    for category, skills in SKILL_CATEGORIES.items():
        if lower in skills:
            return category
    return "other"


def parse_skills_section(blocks: List[DocumentBlock]) -> List[str]:
    """Extract skills from skills section blocks."""
    skills: List[str] = []
    seen: Set[str] = set()

    for i, block in enumerate(blocks):
        # Skip section header block if it's a single line that matches section name
        if i == 0 and len(block.lines) == 1:
            first_line = block.lines[0].text.strip()
            normalized = first_line.lower().strip()
            if normalized in ("skills", "technical skills", "core skills", "competencies", "technical expertise", "technologies", "tech stack"):
                continue
        
        start_line = 1 if (i == 0 and len(block.lines) > 1) else 0
        for line in block.lines[start_line:]:
            text = line.text.strip()
            if not text:
                continue

            # Handle bullet points
            if is_bullet_line(text):
                skill = strip_bullet(text)
                if skill and skill.lower() not in seen:
                    skills.append(skill)
                    seen.add(skill.lower())
                continue

            # Split comma-separated skills
            line_skills = split_skills_line(text)
            for skill in line_skills:
                skill = skill.strip()
                if skill and skill.lower() not in seen:
                    skills.append(skill)
                    seen.add(skill.lower())

    return skills


def extract_skills_from_text(text: str) -> List[str]:
    """Extract skills from arbitrary text using keyword matching."""
    skills = []
    seen = set()
    lower = text.lower()

    # Check all known skills
    for category, skill_set in SKILL_CATEGORIES.items():
        for skill in skill_set:
            # Word boundary match
            pattern = rf"\b{re.escape(skill)}\b"
            if re.search(pattern, lower) and skill not in seen:
                skills.append(skill.title() if len(skill) > 3 else skill.upper())
                seen.add(skill)

    return skills