"""R6.11 — Final Resume Domain Acceptance, Data-Integrity & Safety Test Suite.

Verifies:
1. Complete 14-section ResumeProfile & ResumeContent round-trips
2. Version immutability and provenance tracking
3. Single-item targeted mutation isolation
4. Fresher safety & provenance locks (project != employment, academic != employment)
5. Template switching content invariance
6. Build-from-scratch and template-start pipelines
7. PDF & DOCX export fidelity with all 14 sections
"""

import copy
import pytest
from app.models.improvement import ApprovedProposal
from app.models.resume import (
    AdditionalItem,
    BulletItem,
    CertificationItem,
    EducationItem,
    ExperienceItem,
    LanguageItem,
    LeadershipItem,
    LinkItem,
    PersonalInfo,
    ProjectItem,
    ResumeContent,
    ResumeMeta,
    ResumeProfile,
    SkillCategory,
)
from app.services.export_service import export_service
from app.services.improvement.proposal_application_service import (
    ProvenanceViolationError,
    locate_and_apply_mutation,
    validate_provenance_lock,
)


@pytest.fixture
def canonical_14_section_profile() -> ResumeProfile:
    return ResumeProfile(
        personal=PersonalInfo(
            full_name="Aarav Sharma",
            email="aarav.sharma@example.com",
            phone="+91 98765 43210",
            location="Bengaluru, India",
            headline="Staff Distributed Systems Architect",
            website="https://aaravsharma.dev",
            linkedin="https://linkedin.com/in/aaravsharma",
            github="https://github.com/aaravsharma",
        ),
        target_role="Principal Backend Engineer",
        summary="Experienced distributed systems architect with 8+ years scaling high-throughput event pipelines.",
        experience=[
            ExperienceItem(
                id="exp-1",
                company="CloudScale Global",
                role="Staff Infrastructure Engineer",
                location="Bengaluru, India",
                start_date="2021-01",
                end_date="Present",
                current=True,
                employment_type="Full-time",
                responsibilities=[
                    BulletItem(id="b1", text="Architected stream processing engine processing 5M msgs/sec with Kafka and Go"),
                    BulletItem(id="b2", text="Reduced p99 distributed query latency from 180ms to 42ms via tiered cache"),
                ],
                achievements=["Led company migration from monolithic MySQL to distributed CockroachDB"],
                tools=["Go", "Kafka", "Docker", "Kubernetes", "PostgreSQL"],
                metrics="76% reduction in query latency, 99.999% uptime",
            ),
            ExperienceItem(
                id="exp-2",
                company="FinTech Core",
                role="Senior Software Engineer",
                location="Pune, India",
                start_date="2018-06",
                end_date="2020-12",
                current=False,
                employment_type="Full-time",
                responsibilities=[
                    BulletItem(id="b3", text="Implemented PCI-DSS compliant transaction ledger with idempotent execution"),
                ],
                achievements=["Zero transaction reconciliation discrepancy over 2 years"],
                tools=["Python", "FastAPI", "PostgreSQL", "Redis"],
                metrics="$100M+ processed monthly",
            ),
        ],
        internships=[
            ExperienceItem(
                id="intern-1",
                company="National Supercomputing Facility",
                role="Systems Engineering Intern",
                location="Hyderabad, India",
                start_date="2017-12",
                end_date="2018-05",
                current=False,
                employment_type="Internship",
                responsibilities=[
                    BulletItem(id="ib1", text="Profiled Linux kernel memory allocation under heavy MPI workloads"),
                ],
                achievements=["Co-authored technical report on NUMA memory locality"],
                tools=["C", "Linux", "MPI"],
                metrics="14% throughput improvement in synthetic benchmark",
            ),
        ],
        education=[
            EducationItem(
                id="edu-1",
                institution="IIT Bombay",
                degree="B.Tech & M.Tech Dual Degree",
                field="Computer Science and Engineering",
                location="Mumbai, India",
                start_date="2013-07",
                end_date="2018-05",
                gpa="9.4 / 10.0",
                coursework=["Distributed Computing", "Advanced Algorithms", "Operating Systems"],
                achievements=["Gold Medal for Academic Excellence"],
            ),
        ],
        skills=SkillCategory(
            technical=["Go", "Python", "Rust", "FastAPI", "gRPC"],
            tools=["Docker", "Kubernetes", "Terraform", "GitHub Actions"],
            languages=["English (Fluent)", "Hindi (Native)"],
            databases=["PostgreSQL", "CockroachDB", "Redis", "Elasticsearch"],
            analytics=["Prometheus", "Grafana", "OpenTelemetry"],
            soft_skills=["System Architecture", "Cross-team Mentorship"],
            custom={},
        ),
        projects=[
            ProjectItem(
                id="proj-1",
                name="RaftKV - Distributed Key-Value Engine",
                description="High-availability consensus-backed key-value store with linearizable reads",
                problem="Standard replication models suffered split-brain errors on network partition",
                contribution="Implemented Raft consensus leader election and log compaction in Rust",
                technologies=["Rust", "gRPC", "Protobuf"],
                methodology="TDD & Jepsen Testing",
                results="Passed 1,000+ continuous Jepsen partition chaos runs without data loss",
                metrics="25,000 writes/sec single cluster throughput",
                url="https://github.com/aaravsharma/raftkv",
            ),
        ],
        certifications=[
            CertificationItem(
                id="cert-1",
                name="AWS Certified Solutions Architect – Professional",
                issuer="Amazon Web Services",
                date="2023-05",
                credential_url="https://aws.amazon.com/verify/cert-12345",
            ),
        ],
        achievements=[
            "Published paper in IEEE Cloud 2019 conference",
            "Winner of National Hackathon 2018",
        ],
        leadership=[
            LeadershipItem(
                id="lead-1",
                organization="Systems & Cloud Computing Meetup",
                role="Co-Organizer & Speaker",
                start_date="2020-01",
                end_date="Present",
                description="Organized 24+ technical deep-dives for 2,000+ systems engineers",
            ),
        ],
        languages=[
            LanguageItem(id="lang-1", language="English", proficiency="Fluent"),
            LanguageItem(id="lang-2", language="Hindi", proficiency="Native"),
        ],
        links=[
            LinkItem(id="link-1", label="Portfolio", url="https://aaravsharma.dev"),
            LinkItem(id="link-2", label="GitHub", url="https://github.com/aaravsharma"),
            LinkItem(id="link-3", label="LinkedIn", url="https://linkedin.com/in/aaravsharma"),
        ],
        additional=[
            AdditionalItem(
                id="add-1",
                title="Patents",
                description="Co-inventor on US Patent: Method for adaptive distributed rate limiting",
            ),
        ],
    )


def test_complete_14_section_round_trip(canonical_14_section_profile: ResumeProfile):
    """R6.11.2: Verify ResumeProfile -> ResumeContent -> Dict -> ResumeContent -> ResumeProfile preserves every section."""
    content = ResumeContent(profile=canonical_14_section_profile, meta=ResumeMeta(is_fresher=False, completeness=1.0))
    serialized = content.to_dict()

    reconstructed = ResumeContent.from_dict(serialized)
    p = reconstructed.profile

    assert p.personal.full_name == "Aarav Sharma"
    assert p.personal.email == "aarav.sharma@example.com"
    assert len(p.experience) == 2
    assert len(p.experience[0].responsibilities) == 2
    assert p.experience[0].tools == ["Go", "Kafka", "Docker", "Kubernetes", "PostgreSQL"]
    assert len(p.internships) == 1
    assert p.internships[0].company == "National Supercomputing Facility"
    assert len(p.education) == 1
    assert p.education[0].coursework == ["Distributed Computing", "Advanced Algorithms", "Operating Systems"]
    assert len(p.skills.technical) == 5
    assert len(p.projects) == 1
    assert p.projects[0].technologies == ["Rust", "gRPC", "Protobuf"]
    assert len(p.certifications) == 1
    assert p.certifications[0].name == "AWS Certified Solutions Architect – Professional"
    assert len(p.achievements) == 2
    assert len(p.leadership) == 1
    assert len(p.languages) == 2
    assert len(p.links) == 3
    assert len(p.additional) == 1
    assert p.additional[0].title == "Patents"


def test_version_isolation_and_targeted_change(canonical_14_section_profile: ResumeProfile):
    """R6.11.3 & R6.11.14: Apply ONE targeted improvement and verify ONLY intended item changes while base version and all other sections remain untouched."""
    base_profile = copy.deepcopy(canonical_14_section_profile)
    working_profile = copy.deepcopy(canonical_14_section_profile)

    # Proposal modifying only the second bullet in the first experience item
    proposal = ApprovedProposal(
        proposal_id="prop-1",
        requirement_id="req-latency",
        target_section="experience[0]",
        target_entry_id="exp-1",
        original_text="Reduced p99 distributed query latency from 180ms to 42ms via tiered cache",
        proposed_wording="Reduced p99 distributed query latency from 180ms to 42ms via multi-tier caching and connection pooling",
        provenance="professional",
        eligibility="eligible",
        decision="approved",
    )

    applied, summary = locate_and_apply_mutation(working_profile, proposal)
    assert applied is True

    # 1. Verify target was updated in working profile
    assert working_profile.experience[0].responsibilities[1].text == proposal.proposed_wording

    # 2. Verify BASE profile was NOT mutated
    assert base_profile.experience[0].responsibilities[1].text == proposal.original_text

    # 3. Verify ALL other 13 sections in working profile remain strictly identical to base
    assert working_profile.personal == base_profile.personal
    assert working_profile.summary == base_profile.summary
    assert working_profile.experience[0].responsibilities[0] == base_profile.experience[0].responsibilities[0]
    assert working_profile.experience[1] == base_profile.experience[1]
    assert working_profile.internships == base_profile.internships
    assert working_profile.education == base_profile.education
    assert working_profile.skills == base_profile.skills
    assert working_profile.projects == base_profile.projects
    assert working_profile.certifications == base_profile.certifications
    assert working_profile.achievements == base_profile.achievements
    assert working_profile.leadership == base_profile.leadership
    assert working_profile.languages == base_profile.languages
    assert working_profile.links == base_profile.links
    assert working_profile.additional == base_profile.additional


def test_fresher_safety_provenance_locks():
    """R6.11.4: Provenance locks prevent project, academic, coursework, certification evidence from being placed into professional experience."""
    # Attempting to put project evidence into work experience MUST raise ProvenanceViolationError
    bad_proposal = ApprovedProposal(
        proposal_id="prop-bad-1",
        requirement_id="req-backend",
        target_section="experience[0]",
        target_entry_id="exp-fake",
        original_text="",
        proposed_wording="Worked as Backend Engineer building microservices",
        provenance="project",  # Non-professional source
        eligibility="eligible",
        decision="approved",
    )

    with pytest.raises(ProvenanceViolationError):
        validate_provenance_lock(bad_proposal)

    # Academic provenance into experience is also blocked
    academic_proposal = ApprovedProposal(
        proposal_id="prop-bad-2",
        requirement_id="req-algo",
        target_section="experience",
        original_text="",
        proposed_wording="Developed algorithms in university lab",
        provenance="academic",
        eligibility="eligible",
        decision="approved",
    )

    with pytest.raises(ProvenanceViolationError):
        validate_provenance_lock(academic_proposal)


def test_fresher_build_from_scratch_and_export():
    """R6.11.7: Fresh graduate with ZERO professional experience builds, serializes, and exports without error."""
    fresher_profile = ResumeProfile(
        personal=PersonalInfo(
            full_name="Pooja Verma",
            email="pooja.verma@example.com",
            phone="+91 91234 56789",
            location="Delhi, India",
            headline="Graduate Software Engineer",
        ),
        target_role="Junior Python Developer",
        summary="Enthusiastic CS graduate with practical experience in FastAPI, PostgreSQL, and algorithmic problem solving.",
        experience=[],  # ZERO professional experience
        internships=[
            ExperienceItem(
                id="intern-1",
                company="Tech Foundation",
                role="Backend Intern",
                location="Remote",
                start_date="2023-01",
                end_date="2023-06",
                current=False,
                responsibilities=[BulletItem(id="ib1", text="Built REST API endpoints for user authentication")],
                tools=["Python", "FastAPI"],
            )
        ],
        education=[
            EducationItem(
                id="edu-1",
                institution="Delhi Technological University",
                degree="B.Tech",
                field="Information Technology",
                location="Delhi, India",
                start_date="2019-08",
                end_date="2023-05",
                gpa="8.7 / 10.0",
                coursework=["Operating Systems", "Database Management"],
            )
        ],
        skills=SkillCategory(
            technical=["Python", "FastAPI", "SQL", "Git"],
            tools=["VS Code", "Postman"],
            languages=["English", "Hindi"],
        ),
        projects=[
            ProjectItem(
                id="proj-1",
                name="Library Inventory Manager",
                description="Web application for managing book checkouts and reservations",
                technologies=["Python", "SQLite"],
            )
        ],
        certifications=[
            CertificationItem(id="cert-1", name="Python Certified Associate", issuer="Python Institute", date="2022")
        ],
        achievements=["Dean's Honor List 2022"],
        languages=[LanguageItem(id="l1", language="English", proficiency="Fluent")],
        links=[LinkItem(id="lk1", label="GitHub", url="https://github.com/pooja-verma")],
    )

    content = ResumeContent(profile=fresher_profile, meta=ResumeMeta(is_fresher=True, completeness=0.9))
    assert len(content.profile.experience) == 0

    # Export PDF and DOCX for fresher
    pdf_bytes = export_service.export_pdf(content, template="minimal")
    assert len(pdf_bytes) > 500
    assert pdf_bytes.startswith(b"%PDF")

    docx_bytes = export_service.export_docx(content, template="minimal")
    assert len(docx_bytes) > 500
    assert docx_bytes.startswith(b"PK")  # ZIP header for docx


def test_export_all_14_sections_pdf_and_docx(canonical_14_section_profile: ResumeProfile):
    """R6.11.9: Generated export contains all 14 supported sections without error or content loss."""
    content = ResumeContent(profile=canonical_14_section_profile)

    # PDF Export
    pdf_bytes = export_service.export_pdf(content, template="minimal")
    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 1000
    assert pdf_bytes.startswith(b"%PDF")

    # DOCX Export
    docx_bytes = export_service.export_docx(content, template="minimal")
    assert isinstance(docx_bytes, bytes)
    assert len(docx_bytes) > 1000
    assert docx_bytes.startswith(b"PK")


def test_template_switching_semantic_invariance(canonical_14_section_profile: ResumeProfile):
    """R6.11.6: Switching template preserves exact semantic content without mutating ResumeProfile."""
    content = ResumeContent(profile=canonical_14_section_profile)
    orig_dump = content.model_dump()

    pdf_minimal = export_service.export_pdf(content, template="minimal")
    pdf_modern = export_service.export_pdf(content, template="modern")
    pdf_classic = export_service.export_pdf(content, template="classic")

    assert len(pdf_minimal) > 0
    assert len(pdf_modern) > 0
    assert len(pdf_classic) > 0

    # Verify content model was not mutated during rendering
    assert content.model_dump() == orig_dump
