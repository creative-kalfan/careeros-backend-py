"""Curated static learning roadmap links by skill."""

STATIC_SKILL_ROADMAPS = {
    "python": [
        {"title": "Official Python Tutorial", "url": "https://docs.python.org/3/tutorial/", "type": "documentation"},
        {"title": "Real Python Tutorials", "url": "https://realpython.com/", "type": "guide"},
    ],
    "fastapi": [
        {"title": "FastAPI Official Documentation", "url": "https://fastapi.tiangolo.com/tutorial/", "type": "documentation"},
        {"title": "Full Stack FastAPI Template", "url": "https://github.com/fastapi/full-stack-fastapi-template", "type": "template"},
    ],
    "react": [
        {"title": "React Official Documentation", "url": "https://react.dev/learn", "type": "documentation"},
        {"title": "Full Stack Open: Modern React", "url": "https://fullstackopen.com/en/", "type": "course"},
    ],
    "typescript": [
        {"title": "TypeScript Handbook", "url": "https://www.typescriptlang.org/docs/handbook/intro.html", "type": "handbook"},
        {"title": "Total TypeScript", "url": "https://www.totaltypescript.com/", "type": "guide"},
    ],
    "docker": [
        {"title": "Docker Getting Started", "url": "https://docs.docker.com/get-started/", "type": "documentation"},
    ],
    "postgresql": [
        {"title": "PostgreSQL Tutorial", "url": "https://www.postgresqltutorial.com/", "type": "tutorial"},
    ],
    "aws": [
        {"title": "AWS Skill Builder", "url": "https://explore.skillbuilder.aws/", "type": "course"},
    ],
    "kubernetes": [
        {"title": "Kubernetes Basics", "url": "https://kubernetes.io/docs/tutorials/kubernetes-basics/", "type": "documentation"},
    ],
    "sql": [
        {"title": "SQLBolt: Learn SQL with Simple Interactive Exercises", "url": "https://sqlbolt.com/", "type": "interactive"},
    ],
}


def get_learning_links_for_skills(missing_skills: list[str]) -> list[dict[str, str]]:
    """Return static curated learning links for candidate's missing skills."""
    links = []
    for skill in missing_skills:
        key = skill.strip().lower()
        if key in STATIC_SKILL_ROADMAPS:
            for item in STATIC_SKILL_ROADMAPS[key]:
                links.append({
                    "skill": skill,
                    "title": item["title"],
                    "url": item["url"],
                    "type": item["type"],
                })
        else:
            # Fallback static search link
            links.append({
                "skill": skill,
                "title": f"Learn {skill.title()} Documentation & Guides",
                "url": f"https://devdocs.io/#q={key}",
                "type": "reference",
            })
    return links
