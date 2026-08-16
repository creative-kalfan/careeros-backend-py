"""Test job personalization logic with controlled profiles."""

import pytest
from unittest.mock import Mock, patch
from app.services.jobs.personalized_job_service import PersonalizedJobService
from app.services.jobs.job_relevance_service import JobRelevanceService
from app.models.profile import UserProfile
from app.models.job import NormalizedJob
from app.parsing.role_classifier import classify
from app.parsing.role_taxonomy import normalize_role


class TestPersonalizationLogic:
    """Verify that personalization actually filters and ranks jobs."""

    @pytest.fixture
    def service(self):
        """Create a personalized job service."""
        return PersonalizedJobService()

    @pytest.fixture
    def sample_jobs(self):
        """Create sample jobs with different role categories."""
        return [
            NormalizedJob(
                id="1",
                title="Software Engineer",
                company="Google",
                location="San Francisco",
                role_category="Software Engineering",
                skills=["python", "javascript"],
                description="Build software"
            ),
            NormalizedJob(
                id="2",
                title="Product Manager",
                company="Meta",
                location="San Francisco",
                role_category="Product & Business",
                skills=["strategy", "analytics"],
                description="Manage products"
            ),
            NormalizedJob(
                id="3",
                title="Data Scientist",
                company="Amazon",
                location="Seattle",
                role_category="Data & Analytics",
                skills=["python", "ml", "statistics"],
                description="Analyze data"
            ),
            NormalizedJob(
                id="4",
                title="DevOps Engineer",
                company="Netflix",
                location="Remote",
                role_category="Software Engineering",
                skills=["kubernetes", "terraform"],
                description="Manage infrastructure"
            ),
            NormalizedJob(
                id="5",
                title="UX Designer",
                company="Apple",
                location="Cupertino",
                role_category="Design & Creative",
                skills=["figma", "user research"],
                description="Design experiences"
            ),
            NormalizedJob(
                id="6",
                title="Backend Engineer",
                company="Stripe",
                location="San Francisco",
                role_category="Software Engineering",
                skills=["python", "django", "postgresql"],
                description="Build APIs"
            ),
            NormalizedJob(
                id="7",
                title="Frontend Engineer",
                company="Airbnb",
                location="San Francisco",
                role_category="Software Engineering",
                skills=["react", "typescript"],
                description="Build UI"
            ),
            NormalizedJob(
                id="8",
                title="Machine Learning Engineer",
                company="Tesla",
                location="Palo Alto",
                role_category="Data & Analytics",
                skills=["python", "tensorflow", "ml"],
                description="Build ML models"
            ),
            NormalizedJob(
                id="9",
                title="QA Engineer",
                company="Microsoft",
                location="Redmond",
                role_category="Software Engineering",
                skills=["selenium", "testing"],
                description="Test software"
            ),
            NormalizedJob(
                id="10",
                title="Security Engineer",
                company="Cloudflare",
                location="San Francisco",
                role_category="Software Engineering",
                skills=["security", "networking"],
                description="Secure systems"
            ),
        ]

    def test_filter_jobs_by_desired_role_software_engineer(self, service, sample_jobs):
        """Test that Software Engineer profile filters to Software Engineering jobs."""
        profile = UserProfile(
            id="test-user",
            desired_role="Software Engineer",
            skills=["python", "javascript"],
            location="San Francisco"
        )

        filtered = service.filter_jobs(sample_jobs, profile)

        assert len(filtered) > 0, "Should return some jobs"
        # Primary category + related roles allowed
        for job in filtered:
            assert job.role_category == "Software Engineering" or \
                normalize_role(job.title) in ["DevOps Engineer", "Site Reliability Engineer", "Platform Engineer", "Solutions Architect"], \
                f"Unexpected role: {job.role_category} for {job.title}"

        print(f"\n✅ Software Engineer profile filtered to {len(filtered)} jobs (primary + related)")
        for job in filtered:
            print(f"   - {job.title} at {job.company} ({job.role_category})")

    def test_filter_jobs_by_desired_role_data_scientist(self, service, sample_jobs):
        """Test that Data Scientist profile filters to Data & Analytics jobs."""
        profile = UserProfile(
            id="test-user",
            desired_role="Data Scientist",
            skills=["python", "ml"],
            location="Seattle"
        )

        filtered = service.filter_jobs(sample_jobs, profile)

        assert len(filtered) > 0, "Should return some jobs"
        assert all(job.role_category == "Data & Analytics" for job in filtered), \
            f"All jobs should be Data & Analytics, got: {[j.role_category for j in filtered]}"

        print(f"\n✅ Data Scientist profile filtered to {len(filtered)} Data & Analytics jobs")
        for job in filtered:
            print(f"   - {job.title} at {job.company}")

    def test_filter_jobs_by_desired_role_product_manager(self, service, sample_jobs):
        """Test that Product Manager profile filters to Product & Business jobs + related."""
        profile = UserProfile(
            id="test-user",
            desired_role="Product Manager",
            skills=["strategy", "analytics"],
            location="San Francisco"
        )

        filtered = service.filter_jobs(sample_jobs, profile)

        assert len(filtered) > 0, "Should return some jobs"
        for job in filtered:
            assert job.role_category == "Product & Business" or \
                normalize_role(job.title) in ["Business Analyst", "Project Manager", "Program Manager", "UX Designer"], \
                f"Unexpected role: {job.role_category} for {job.title}"

        print(f"\n✅ Product Manager profile filtered to {len(filtered)} jobs (primary + related)")
        for job in filtered:
            print(f"   - {job.title} at {job.company} ({job.role_category})")

    def test_different_profiles_return_different_jobs(self, service, sample_jobs):
        """Test that different profiles return different job sets."""
        sw_eng_profile = UserProfile(
            id="test-user-1",
            desired_role="Software Engineer",
            skills=["python"],
            location="San Francisco"
        )

        data_scientist_profile = UserProfile(
            id="test-user-2",
            desired_role="Data Scientist",
            skills=["python", "ml"],
            location="Seattle"
        )

        sw_eng_jobs = service.filter_jobs(sample_jobs, sw_eng_profile)
        data_scientist_jobs = service.filter_jobs(sample_jobs, data_scientist_profile)

        # The two profiles should return different jobs
        sw_eng_titles = {job.title for job in sw_eng_jobs}
        data_scientist_titles = {job.title for job in data_scientist_jobs}

        # Software Engineer should only have Software Engineering jobs
        # Data Scientist should only have Data Science jobs
        # So they should be different
        assert sw_eng_titles != data_scientist_titles, \
            "Software Engineer and Data Scientist profiles should return different jobs"

        print(f"\n✅ Different profiles return different jobs:")
        print(f"   Software Engineer: {len(sw_eng_jobs)} jobs - {sw_eng_titles}")
        print(f"   Data Scientist: {len(data_scientist_jobs)} jobs - {data_scientist_titles}")
        print(f"   Overlap: {len(sw_eng_titles & data_scientist_titles)}")

    def test_no_desired_role_returns_all_jobs(self, service, sample_jobs):
        """Test that no desired role returns all jobs."""
        profile = UserProfile(
            id="test-user",
            desired_role=None,
            skills=[],
            location=None
        )

        filtered = service.filter_jobs(sample_jobs, profile)

        # Should return all jobs
        assert len(filtered) == len(sample_jobs), \
            f"Should return all {len(sample_jobs)} jobs when no desired role, got {len(filtered)}"

        print(f"\n✅ No desired role returns all {len(filtered)} jobs")

    def test_calculate_match_score_software_engineer(self, service):
        """Test match score calculation for Software Engineer."""
        profile = UserProfile(
            id="test-user",
            desired_role="Software Engineer",
            skills=["python", "javascript", "react"],
            location="San Francisco",
            preferred_companies=["Google", "Meta"]
        )

        # Job with matching title
        job1 = NormalizedJob(
            id="1",
            title="Software Engineer",
            company="Google",
            location="San Francisco",
            role_category="Software Engineering",
            skills=["python", "javascript", "react", "node.js"],
            description="Build software"
        )

        # Job with non-matching title
        job2 = NormalizedJob(
            id="2",
            title="Product Manager",
            company="Google",
            location="San Francisco",
            role_category="Product Management",
            skills=["strategy"],
            description="Manage products"
        )

        score1 = service.calculate_match_score(job1, profile)
        score2 = service.calculate_match_score(job2, profile)

        # Job 1 should have higher score (title match + skill match + location match + company match)
        assert score1["overall"] > score2["overall"], \
            f"Software Engineer job should score higher ({score1['overall']}) than PM job ({score2['overall']})"

        # Job 1 should have resume_match = 100 (title contains "Software Engineer")
        assert score1["resume_match"] == 100, \
            f"Software Engineer job should have resume_match=100, got {score1['resume_match']}"

        # Job 2 should have resume_match = 0 (title doesn't contain "Software Engineer")
        assert score2["resume_match"] == 0, \
            f"PM job should have resume_match=0, got {score2['resume_match']}"

        print(f"\n✅ Match scores calculated correctly:")
        print(f"   Software Engineer job: {score1['overall']} (resume_match: {score1['resume_match']})")
        print(f"   Product Manager job: {score2['overall']} (resume_match: {score2['resume_match']})")

    def test_match_score_ranking(self, service):
        """Test that jobs are ranked by match score."""
        profile = UserProfile(
            id="test-user",
            desired_role="Software Engineer",
            skills=["python", "javascript"],
            location="San Francisco",
            preferred_companies=["Google"]
        )

        jobs = [
            NormalizedJob(
                id="1",
                title="Software Engineer at Google",
                company="Google",
                location="San Francisco",
                role_category="Software Engineering",
                skills=["python", "javascript"],
                description="Build software"
            ),
            NormalizedJob(
                id="2",
                title="Software Engineer at Amazon",
                company="Amazon",
                location="Seattle",
                role_category="Software Engineering",
                skills=["python", "java"],
                description="Build software"
            ),
            NormalizedJob(
                id="3",
                title="Product Manager at Google",
                company="Google",
                location="San Francisco",
                role_category="Product Management",
                skills=["strategy"],
                description="Manage products"
            ),
        ]

        # Calculate scores
        for job in jobs:
            job.match = service.calculate_match_score(job, profile)

        # Sort by score (descending)
        jobs.sort(key=lambda j: j.match.get("overall", 0) if j.match else 0, reverse=True)

        # First job should have highest score
        scores = [job.match["overall"] for job in jobs]
        assert scores == sorted(scores, reverse=True), \
            f"Jobs should be sorted by score descending: {scores}"

        # First job should be "Software Engineer at Google" (best match)
        # It has: title match + skill match + location match + company match
        assert jobs[0].title == "Software Engineer at Google", \
            f"First job should be 'Software Engineer at Google', got '{jobs[0].title}' (score: {jobs[0].match['overall']})"

        print(f"\n✅ Jobs ranked correctly by match score:")
        for i, job in enumerate(jobs, 1):
            print(f"   {i}. {job.title} (score: {job.match['overall']})")

    def test_role_classifier_integration(self):
        """Test that role classifier maps desired roles to categories correctly."""
        test_cases = [
            ("Software Engineer", "Software Engineering"),
            ("Data Scientist", "Data & Analytics"),
            ("Product Manager", "Product & Business"),
            ("DevOps Engineer", "Software Engineering"),
            ("UX Designer", "Design & Creative"),
            ("QA Engineer", "Software Engineering"),
            ("Security Engineer", "Software Engineering"),
            ("Engineering Manager", "Management"),
            ("Mobile Developer", "Software Engineering"),
            ("Unknown Role", "Other"),
        ]

        print(f"\n✅ Role classifier mapping:")
        for role, expected_category in test_cases:
            actual = classify(role)
            assert actual == expected_category, \
                f"'{role}' should map to '{expected_category}', got '{actual}'"
            print(f"   {role} → {actual}")

    def test_empty_profile_returns_all_jobs(self, service, sample_jobs):
        """Test that empty profile returns all jobs without crashing."""
        profile = None

        filtered = service.filter_jobs(sample_jobs, profile)

        # Should return all jobs
        assert len(filtered) == len(sample_jobs), \
            f"Should return all {len(sample_jobs)} jobs with no profile, got {len(filtered)}"

        print(f"\n✅ Empty profile returns all {len(filtered)} jobs")

    def test_match_score_with_no_profile(self, service):
        """Test that match score returns zeros with no profile."""
        job = NormalizedJob(
            id="1",
            title="Software Engineer",
            company="Google",
            location="San Francisco",
            role_category="Software Engineering",
            skills=["python"],
            description="Build software"
        )

        score = service.calculate_match_score(job, None)

        # All scores should be 0
        assert all(v == 0 for v in score.values()), \
            f"All scores should be 0 with no profile, got {score}"

        print(f"\n✅ Match score with no profile returns all zeros: {score}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])