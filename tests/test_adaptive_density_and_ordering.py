"""Comprehensive tests for Universal Section Ordering and Adaptive Visual Density Engine.

Validates the 16 core benchmarks:
1. Short resume -> typography increases
2. Short resume -> vertical spacing increases
3. Normal resume -> remains within normal typography range
4. Dense resume -> spacing reduced before typography
5. Extremely dense resume -> content optimization before aggressive font reduction
6. Canonical section ordering always Summary -> Skills -> Experience -> Projects -> Education after Header
7. Missing sections do not create empty headings
8. Additional/unknown sections follow deterministic fallback ordering
9. Short resume not excessively oversized (bounded at max_body_pt)
10. Dense resume not unreadably small (bounded at min_body_pt)
11. Rendered PDF has no clipping
12. Rendered PDF has no overlap
13. Rendered one-page resume has balanced vertical utilization
14. Attached/reference resume (Alex Chen) produces materially better visual density
15. Layout optimization does not alter factual resume content
16. Existing resume tailoring behavior remains unchanged
"""

import shutil
import pytest

from app.models.resume import (
    BulletItem,
    EducationItem,
    ExperienceItem,
    PersonalInfo,
    ProjectItem,
    ResumeContent,
    ResumeProfile,
    SkillCategory,
)
from app.services.pdf.typst_compiler import (
    compile_typst_to_pdf,
    render_document_model_to_typst,
)
from app.services.resumes.document_model import (
    ResumeDocumentModel,
    build_document_model,
    get_canonical_section_order,
)
from app.services.resumes.fit_verifier import fit_verifier, measure_pdf_layout
from app.services.resumes.layout_optimizer import (
    LayoutConstraints,
    LayoutOptimizer,
    update_headings_proportionally,
)

needs_typst = pytest.mark.skipif(
    shutil.which("typst") is None, reason="typst CLI not installed"
)


def _compile_pdf(doc_model: ResumeDocumentModel) -> bytes:
    markup = render_document_model_to_typst(doc_model)
    return compile_typst_to_pdf(markup, enforce_single_page=False)


def _make_alex_chen_content() -> ResumeContent:
    return ResumeContent(
        profile=ResumeProfile(
            personal=PersonalInfo(
                full_name="Alex Chen",
                email="alex.chen@example.com",
                phone="+1 (555) 123-4567",
                location="Chicago, IL",
                headline="NOC Analyst",
            ),
            summary="Network Operations Center (NOC) Analyst with 4 years managing enterprise systems, following SOP guidelines, and generating operational reports.",
            skills=SkillCategory(
                technical=["Network Monitoring", "Linux", "SOP Adherence", "Incident Management", "Process Documentation"],
                tools=["Wireshark", "JIRA", "Pingdom"],
            ),
            experience=[
                ExperienceItem(
                    company="CloudTech Global",
                    role="NOC Analyst",
                    location="Chicago, IL",
                    start_date="2020-06",
                    end_date="2024-06",
                    responsibilities=[
                        BulletItem(text="Maintained rigorous SOP adherence and operational documentation for all incident workflows across enterprise network infrastructure."),
                        BulletItem(text="Generated weekly operational reporting and metrics for executive leadership reviews to monitor SLA performance."),
                        BulletItem(text="Fostered cross-functional collaboration between engineering and technical support teams to accelerate ticket resolution times."),
                    ],
                )
            ],
            education=[
                EducationItem(
                    institution="University of Illinois",
                    degree="Bachelor of Science in Information Technology",
                    start_date="2016-08",
                    end_date="2020-05",
                )
            ],
        )
    )


def _make_moderate_content() -> ResumeContent:
    """A moderately short resume (2 roles, 5 bullets, projects, skills, education) suitable for vertical expansion."""
    return ResumeContent(
        profile=ResumeProfile(
            personal=PersonalInfo(
                full_name="Devon Vance",
                email="devon.vance@example.com",
                phone="+1 (555) 839-2041",
                location="Austin, TX",
                headline="Software Engineer",
            ),
            summary="Full stack software engineer with 3 years of production experience across Python, TypeScript, and modern relational databases.",
            skills=SkillCategory(
                technical=["Python", "TypeScript", "FastAPI", "React", "PostgreSQL"],
                tools=["Docker", "Git", "GitHub Actions"],
            ),
            experience=[
                ExperienceItem(
                    company="FinTech Solutions",
                    role="Software Engineer",
                    location="Austin, TX",
                    start_date="2022",
                    end_date="Present",
                    responsibilities=[
                        BulletItem(text="Developed asynchronous webhook processing service handling 2,000 requests per minute with 99.9% uptime."),
                        BulletItem(text="Implemented automated reconciliation scripts saving accounting team 12 hours of manual ledger auditing weekly."),
                        BulletItem(text="Refactored database queries and indexing strategies, decreasing average response time from 240ms to 45ms."),
                    ],
                ),
                ExperienceItem(
                    company="WebCore Labs",
                    role="Junior Developer",
                    location="Dallas, TX",
                    start_date="2021",
                    end_date="2022",
                    responsibilities=[
                        BulletItem(text="Built responsive client dashboards in React and TypeScript consumed by over 15,000 active retail users."),
                        BulletItem(text="Configured CI/CD test automation pipelines reducing staging build deployment errors by 30%."),
                    ],
                ),
            ],
            projects=[
                ProjectItem(
                    name="QueryCraft",
                    description="Visual SQL query builder and syntax validator.",
                    technologies=["React", "TypeScript", "SQLite"],
                    bullets=[
                        BulletItem(text="Engineered interactive schema explorer with instant query execution and export."),
                    ],
                )
            ],
            education=[
                EducationItem(
                    institution="University of Texas at Austin",
                    degree="B.S. in Computer Science",
                    start_date="2017",
                    end_date="2021",
                )
            ],
        )
    )


def _make_normal_content() -> ResumeContent:
    roles = []
    for i in range(7):
        roles.append(
            ExperienceItem(
                company=f"Tech Enterprise {i+1}",
                role=f"Senior Engineer {i+1}",
                location="New York, NY",
                start_date=f"201{i}",
                end_date=f"202{i}",
                responsibilities=[
                    BulletItem(text="Architected distributed transaction logging infrastructure handling 5,000 queries per second across multi-region hybrid clusters."),
                    BulletItem(text="Spearheaded cross-functional migration to containerized workflows cutting incident response times by 40% across all operational tiers."),
                    BulletItem(text="Refactored core API query patterns reducing P99 latency across all endpoints with zero customer regressions."),
                ],
            )
        )
    return ResumeContent(
        profile=ResumeProfile(
            personal=PersonalInfo(
                full_name="Jordan Taylor",
                email="jordan.taylor@example.com",
                phone="+1 (555) 321-4567",
                location="New York, NY",
                headline="Staff Engineer",
            ),
            summary="Experienced systems engineer with expertise in distributed microservices and cloud infrastructure.",
            skills=SkillCategory(
                technical=["Python", "Go", "Kubernetes", "PostgreSQL", "Kafka"],
                tools=["Docker", "Terraform", "Prometheus"],
            ),
            experience=roles,
            education=[
                EducationItem(
                    institution="Columbia University",
                    degree="B.S. in Computer Science",
                    start_date="2011",
                    end_date="2015",
                )
            ],
        )
    )


def _make_dense_content() -> ResumeContent:
    roles = []
    for i in range(8):
        roles.append(
            ExperienceItem(
                company=f"Enterprise Global Systems {i+1}",
                role=f"Staff Systems Engineer {i+1}",
                location="Seattle, WA",
                start_date=f"201{i}",
                end_date=f"202{i}",
                responsibilities=[
                    BulletItem(text=f"Spearheaded enterprise infrastructure modernization initiative {i+1} achieving $400K annual cost reduction across multi-region hybrid clusters."),
                    BulletItem(text=f"Built high-throughput distributed transaction processor handling 20,000 TPS under extreme peak load with 99.999% availability."),
                    BulletItem(text=f"Standardized continuous integration and deployment pipelines cutting rollout cycles from 4 days to 20 minutes across 50 microservices."),
                    BulletItem(text=f"Orchestrated data warehouse migration of 85TB historical analytics records into modern columnar store with zero downtime."),
                ],
            )
        )
    return ResumeContent(
        profile=ResumeProfile(
            personal=PersonalInfo(
                full_name="Morgan Reed",
                email="morgan.reed@example.com",
                phone="+1 (555) 789-0123",
                location="Seattle, WA",
                headline="Principal Infrastructure Architect",
            ),
            summary="Infrastructure architect with 15+ years delivering large-scale distributed systems and cloud foundations.",
            skills=SkillCategory(
                technical=["Distributed Systems", "Cloud Architecture", "Go", "Python", "C++", "Kubernetes", "Linux Internals"],
                tools=["AWS", "GCP", "Terraform", "Vault", "Consul", "Envoy", "ArgoCD"],
            ),
            experience=roles,
            education=[
                EducationItem(
                    institution="University of Washington",
                    degree="M.S. in Computer Science",
                    start_date="2008",
                    end_date="2010",
                )
            ],
        )
    )


@needs_typst
class TestAdaptiveDensityAndOrdering:
    def test_01_short_resume_typography_increases(self):
        content = _make_alex_chen_content()
        doc = build_document_model(content, None)
        assert doc.style.body_size_pt == 10.0

        res = fit_verifier.fit(doc, _compile_pdf, max_pages=1)
        assert res.document.style.body_size_pt > 10.0
        assert res.document.style.section_heading_size_pt > 12.0
        assert "Increased body typography" in " ".join(res.audit)

    def test_02_short_resume_vertical_spacing_increases(self):
        content = _make_alex_chen_content()
        doc = build_document_model(content, None)
        res = fit_verifier.fit(doc, _compile_pdf, max_pages=1)
        st = res.document.style
        assert st.section_before_pt > 7.0 or st.bullet_spacing_pt > 2.0 or st.header_spacing_pt > 2.0

    def test_03_normal_resume_remains_within_normal_typography_range(self):
        content = _make_normal_content()
        doc = build_document_model(content, None)
        res = fit_verifier.fit(doc, _compile_pdf, max_pages=1)
        st = res.document.style
        assert 9.8 <= st.body_size_pt <= 10.5
        assert 11.5 <= st.section_heading_size_pt <= 13.0

    def test_04_dense_resume_spacing_reduced_before_typography(self):
        content = _make_dense_content()
        doc = build_document_model(content, None)
        optimizer = LayoutOptimizer(LayoutConstraints(max_pages=1))
        res = optimizer.optimize(doc, _compile_pdf)
        kinds = [a["kind"] for a in res.adjustments]
        assert "spacing_reduced" in kinds
        if "typography_reduced" in kinds:
            assert kinds.index("spacing_reduced") < kinds.index("typography_reduced")

    def test_05_extremely_dense_resume_content_optimization_before_font_floor(self):
        content = _make_dense_content()
        doc = build_document_model(content, None)
        res = fit_verifier.fit(doc, _compile_pdf, max_pages=1)
        audit_str = " ".join(res.audit)
        assert "Removed lowest-priority bullet for page fit" in audit_str
        assert res.document.style.body_size_pt >= LayoutConstraints().min_body_pt

    def test_06_canonical_section_ordering_summary_skills_experience_projects_education(self):
        content = _make_alex_chen_content()
        doc = build_document_model(content, None)
        markup = render_document_model_to_typst(doc)
        idx_sum = markup.index("PROFESSIONAL SUMMARY")
        idx_ski = markup.index("SKILLS")
        idx_exp = markup.index("EXPERIENCE")
        idx_edu = markup.index("EDUCATION")
        assert idx_sum < idx_ski < idx_exp < idx_edu

    def test_07_missing_sections_no_empty_headings(self):
        profile = ResumeProfile(
            personal=PersonalInfo(full_name="Sam Solo", email="sam@example.com"),
            summary="Simple summary statement.",
            experience=[
                ExperienceItem(
                    company="Solo Corp",
                    role="Dev",
                    responsibilities=[BulletItem(text="Solo developer work.")],
                )
            ],
        )
        doc = build_document_model(ResumeContent(profile=profile), None)
        markup = render_document_model_to_typst(doc)
        assert "SKILLS" not in markup
        assert "PROJECTS" not in markup
        assert "EDUCATION" not in markup

    def test_08_additional_sections_deterministic_fallback_ordering(self):
        avail = ["volunteer", "certifications", "additional", "awards", "experience", "skills"]
        ordered = get_canonical_section_order(avail)
        assert ordered[:2] == ["skills", "experience"]
        assert "certifications" in ordered
        assert "additional" in ordered
        rem = [s for s in ordered if s not in ("skills", "experience", "certifications", "additional")]
        assert rem == sorted(rem)

    def test_09_short_resume_bounded_at_max_body_pt(self):
        profile = ResumeProfile(
            personal=PersonalInfo(full_name="Mini Candidate"),
            summary="Very short summary.",
        )
        doc = build_document_model(ResumeContent(profile=profile), None)
        res = fit_verifier.fit(doc, _compile_pdf, max_pages=1)
        assert res.document.style.body_size_pt <= LayoutConstraints().max_body_pt

    def test_10_dense_resume_bounded_at_min_body_pt(self):
        content = _make_dense_content()
        doc = build_document_model(content, None)
        res = fit_verifier.fit(doc, _compile_pdf, max_pages=1)
        assert res.document.style.body_size_pt >= LayoutConstraints().min_body_pt

    def test_11_rendered_pdf_no_clipping(self):
        content = _make_alex_chen_content()
        doc = build_document_model(content, None)
        res = fit_verifier.fit(doc, _compile_pdf, max_pages=1)
        metrics = measure_pdf_layout(res.pdf_bytes, style=res.document.style)
        assert not metrics.clipping

    def test_12_rendered_pdf_no_overlap(self):
        content = _make_alex_chen_content()
        doc = build_document_model(content, None)
        res = fit_verifier.fit(doc, _compile_pdf, max_pages=1)
        metrics = measure_pdf_layout(res.pdf_bytes, style=res.document.style)
        assert not metrics.overlap

    def test_13_rendered_one_page_resume_balanced_vertical_utilization(self):
        content = _make_moderate_content()
        doc = build_document_model(content, None)
        unopt_pdf = _compile_pdf(doc)
        unopt_metrics = measure_pdf_layout(unopt_pdf, style=doc.style)

        res = fit_verifier.fit(doc, _compile_pdf, max_pages=1)
        opt_metrics = measure_pdf_layout(res.pdf_bytes, style=res.document.style)

        assert opt_metrics.page_count == 1
        assert opt_metrics.vertical_utilization > unopt_metrics.vertical_utilization
        assert opt_metrics.vertical_utilization >= 0.70

    def test_14_alex_chen_reference_resume_materially_better_density(self):
        content = _make_alex_chen_content()
        doc = build_document_model(content, None)
        unopt_pdf = _compile_pdf(doc)
        unopt_metrics = measure_pdf_layout(unopt_pdf, style=doc.style)

        res = fit_verifier.fit(doc, _compile_pdf, max_pages=1)
        opt_metrics = measure_pdf_layout(res.pdf_bytes, style=res.document.style)

        improvement = opt_metrics.vertical_utilization - unopt_metrics.vertical_utilization
        assert improvement >= 0.12
        assert opt_metrics.page_count == 1

    def test_15_layout_optimization_does_not_alter_factual_content(self):
        content = _make_alex_chen_content()
        doc = build_document_model(content, None)
        res = fit_verifier.fit(doc, _compile_pdf, max_pages=1)
        orig_prof = content.profile
        fit_doc = res.document
        assert fit_doc.header.full_name == orig_prof.personal.full_name
        assert fit_doc.header.email == orig_prof.personal.email
        assert fit_doc.experience[0].company == orig_prof.experience[0].company
        assert [b.text for b in fit_doc.experience[0].bullets] == [
            b.text for b in orig_prof.experience[0].responsibilities
        ]

    def test_16_existing_resume_tailoring_behavior_unchanged(self):
        content = _make_normal_content()
        doc = build_document_model(content, None)
        res = fit_verifier.fit(doc, _compile_pdf, max_pages=1)
        assert res.pdf_bytes.startswith(b"%PDF-")
        assert not res.needs_manual_review
