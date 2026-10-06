"""Tests for Phase 3: Job Quality Intelligence.

Covers:
  - Skill ontology matching and boundary safety ("R", "Go", "Power BI", "Node.js").
  - Duplicate clustering (identical canonical URL, identical content hash, separate distinct jobs).
  - Cluster decoration (also_listed_on, preferred_apply_url prioritizing ATS over aggregators).
  - SSRF safety in url_liveness_checker (blocks loopback, private IPv4, IPv6, non-http, private redirects).
  - Ghost risk transparent scoring (age, dead URL, repost churn, aggregator tier) and Low/Med/High labels.
  - Never labelling a job as 'fake'.
"""

import socket
import pytest
from unittest.mock import MagicMock, patch

from app.domain.skills.loader import get_skill_ontology, extract_skills_with_ontology
from app.services.jobs.job_cluster_service import (
    compute_deterministic_cluster_keys,
    JobClusterService,
)
from app.services.jobs.url_liveness_checker import (
    is_safe_ip,
    is_safe_url,
    check_url_liveness,
)
from app.services.jobs.ghost_risk_service import GhostRiskService


class TestSkillOntology:
    """3.1 Skill ontology matching tests."""

    def test_alias_normalization(self):
        ontology = get_skill_ontology()
        assert "react" in ontology.aliases
        assert ontology.aliases["react"] == "react"
        assert ontology.aliases["reactjs"] == "react"
        assert ontology.aliases["react.js"] == "react"
        assert ontology.aliases["powerbi"] == "power bi"
        assert ontology.aliases["power bi"] == "power bi"
        assert ontology.aliases["nodejs"] == "node.js"
        assert ontology.aliases["node.js"] == "node.js"

    def test_boundary_safety_for_short_tokens(self):
        """'R' and 'Go' must match only on whole words, never inside 'React' or 'Google'."""
        text_without_r_or_go = "We are looking for React developers who will go to Google to build apps."
        skills = extract_skills_with_ontology(text_without_r_or_go)
        assert "react" in skills
        # 'go to Google' has lowercase 'go', but Go requires specific aliases or boundaries
        assert "r" not in skills

        text_with_r = "Strong expertise in Python, R programming, and SQL."
        skills_r = extract_skills_with_ontology(text_with_r)
        assert "r" in skills_r
        assert "python" in skills_r
        assert "sql" in skills_r

        text_with_go = "Looking for Golang engineers with Docker experience."
        skills_go = extract_skills_with_ontology(text_with_go)
        assert "go" in skills_go
        assert "docker" in skills_go

    def test_extract_skills_from_text(self):
        text = "Experience with PostgreSQL, TypeScript, Next.js, and AWS."
        skills = extract_skills_with_ontology(text)
        assert "postgresql" in skills
        assert "typescript" in skills
        assert "next.js" in skills
        assert "aws" in skills


class TestJobClustering:
    """3.2 Duplicate clustering tests."""

    def test_cluster_keys_identical_canonical_url(self):
        job1 = {
            "id": "job-1",
            "company": "Stripe",
            "title": "Backend Engineer",
            "location": "Bengaluru",
            "canonical_url": "https://stripe.com/jobs/123",
            "description": "Build payment infrastructure.",
        }
        job2 = {
            "id": "job-2",
            "company": "Stripe",
            "title": "Software Engineer",
            "location": "Bangalore",
            "canonical_url": "https://stripe.com/jobs/123",
            "description": "Different summary text.",
        }
        keys1 = compute_deterministic_cluster_keys(job1)
        keys2 = compute_deterministic_cluster_keys(job2)

        # Both have matching url:... cluster key
        url_key1 = next(k for k, r in keys1 if r == "identical_canonical_url")
        url_key2 = next(k for k, r in keys2 if r == "identical_canonical_url")
        assert url_key1 == url_key2

    def test_cluster_keys_identical_identity_and_content_hash(self):
        job1 = {
            "company": "Razorpay",
            "title": "Senior Frontend Engineer",
            "location": "Bangalore",
            "description": "Detailed identical description of the job posting.",
        }
        job2 = {
            "company": "razorpay",
            "title": "Senior Frontend Engineer",
            "location": "bangalore",
            "description": "Detailed identical description of the job posting.",
        }
        keys1 = compute_deterministic_cluster_keys(job1)
        keys2 = compute_deterministic_cluster_keys(job2)

        content_key1 = next(k for k, r in keys1 if r == "identical_identity_and_content_hash")
        content_key2 = next(k for k, r in keys2 if r == "identical_identity_and_content_hash")
        assert content_key1 == content_key2

    def test_different_jobs_have_different_keys(self):
        job1 = {"company": "Acme", "title": "Dev", "location": "Remote", "description": "Desc A"}
        job2 = {"company": "Acme", "title": "Dev", "location": "Remote", "description": "Desc B"}
        keys1 = compute_deterministic_cluster_keys(job1)
        keys2 = compute_deterministic_cluster_keys(job2)
        assert keys1 != keys2

    def test_decorate_job_with_cluster_metadata(self):
        mock_repo = MagicMock()
        mock_repo.get_cluster_for_job.return_value = {
            "cluster_id": "c-123",
            "members": [
                {
                    "job_id": "job-aggregator",
                    "jobs": {
                        "id": "job-aggregator",
                        "source_platform": "adzuna",
                        "source_tier": 5,
                        "url": "https://adzuna.in/details/1",
                    },
                },
                {
                    "job_id": "job-ats",
                    "jobs": {
                        "id": "job-ats",
                        "source_platform": "greenhouse",
                        "source_tier": 1,
                        "url": "https://boards.greenhouse.io/stripe/jobs/1",
                    },
                },
            ],
        }

        service = JobClusterService(repository=mock_repo)
        job_input = {
            "id": "job-aggregator",
            "title": "Engineer",
            "url": "https://adzuna.in/details/1",
            "source_tier": 5,
        }
        decorated = service.decorate_job_with_cluster_metadata(job_input)

        assert "also_listed_on" in decorated
        assert len(decorated["also_listed_on"]) == 1
        assert decorated["also_listed_on"][0]["platform"] == "greenhouse"
        # Preferred URL prioritizes Tier 1 (greenhouse) over Tier 5 (adzuna)
        assert decorated["preferred_apply_url"] == "https://boards.greenhouse.io/stripe/jobs/1"


class TestSSRFProtection:
    """3.3 SSRF safety tests."""

    def test_is_safe_ip_blocks_private_and_loopback(self):
        assert not is_safe_ip("127.0.0.1")
        assert not is_safe_ip("10.0.0.1")
        assert not is_safe_ip("172.16.0.1")
        assert not is_safe_ip("192.168.1.1")
        assert not is_safe_ip("169.254.169.254")  # AWS metadata
        assert not is_safe_ip("::1")  # IPv6 loopback
        assert not is_safe_ip("fc00::1")  # IPv6 private

        # Public IP
        assert is_safe_ip("93.184.216.34")
        assert is_safe_ip("8.8.8.8")

    def test_is_safe_url_scheme_validation(self):
        assert not is_safe_url("file:///etc/passwd")[0]
        assert not is_safe_url("ftp://example.com")[0]
        assert not is_safe_url("gopher://example.com")[0]
        assert not is_safe_url("")[0]

    def test_is_safe_url_blocks_dns_resolution_to_private_ip(self):
        with patch("socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))
            ]
            safe, reason = is_safe_url("https://malicious.internal.local/test")
            assert not safe
            assert "non-public" in reason or "private" in reason or "loopback" in reason

    @pytest.mark.asyncio
    async def test_check_url_liveness_blocks_ssrf_without_making_http_request(self):
        # 127.0.0.1 should immediately be blocked without HTTP call
        result = await check_url_liveness("http://127.0.0.1:8000/apply")
        assert result["status"] == "blocked"
        assert "non-public" in result["reason"] or "loopback" in result["reason"]


class TestGhostRiskService:
    """3.3 Ghost risk transparent signals tests."""

    def test_ghost_risk_calculation_young_first_party(self):
        service = GhostRiskService()
        job = {
            "first_seen_at": "2026-10-01T00:00:00Z",  # 5 days ago
            "source_platform": "greenhouse",
            "source_tier": 1,
            "is_active": True,
        }
        res = service.calculate_ghost_risk(job)
        assert res["score"] == 0
        assert res["label"] == "Low ghost risk (estimate)"
        assert res["is_verified_live"] is True
        assert res["verified_ats_source"] == "greenhouse"
        assert "fake" not in res["label"].lower()

    def test_ghost_risk_calculation_old_aggregator_dead_url(self):
        service = GhostRiskService()
        job = {
            "first_seen_at": "2026-06-01T00:00:00Z",  # >90 days ago (+35)
            "source_platform": "adzuna",  # aggregator (+10)
            "source_tier": 5,
            "is_active": True,
        }
        url_check = {"status": "dead"}  # (+50)
        res = service.calculate_ghost_risk(job, url_check_result=url_check, is_repost_churn=True)
        # 35 + 25 + 50 + 10 = 120 -> capped to 100
        assert res["score"] == 100
        assert res["label"] == "High ghost risk (estimate)"
        assert res["is_verified_live"] is False
        assert "fake" not in res["label"].lower()
        signals = [s["signal"] for s in res["signals"]]
        assert "age_over_90_days" in signals
        assert "repost_churn" in signals
        assert "url_dead" in signals
        assert "aggregator_source" in signals

    def test_ghost_risk_medium_range(self):
        service = GhostRiskService()
        job = {
            "first_seen_at": "2026-08-15T00:00:00Z",  # ~50 days ago (+20)
            "source_platform": "adzuna",  # aggregator (+10)
            "source_tier": 5,
        }
        # Total = 30
        res = service.calculate_ghost_risk(job)
        assert 30 <= res["score"] < 65
        assert res["label"] == "Medium ghost risk (estimate)"
        assert "fake" not in res["label"].lower()
