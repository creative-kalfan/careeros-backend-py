"""Regression: column probes must be cached at module level.

get_job_relevance_service() constructs a new JobRepository every request.
Without a module-level cache, each request re-ran schema SELECT probes
(~1s cold / repeated warm network RTT) — a large share of feed latency.
"""

from __future__ import annotations

from app.repositories import job_repository as jr


class _FakeResult:
    def __init__(self) -> None:
        self.data = [{"last_seen_at": None, "source_tier": 1, "mass_hiring": None}]


class _FakeQuery:
    def select(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        return _FakeResult()


class _FakeTable:
    def select(self, *a, **k):
        return _FakeQuery()


class _FakeClient:
    rest_url = "https://example.supabase.co/rest/v1"

    def __init__(self) -> None:
        self.select_calls = 0

    def table(self, name: str):
        self.select_calls += 1
        return _FakeTable()


def test_probe_results_are_cached_across_repository_instances():
    jr.JobRepository.clear_probe_cache()
    client = _FakeClient()

    r1 = jr.JobRepository(client=client)
    assert r1._probe_has_last_seen_at() is True
    assert r1._probe_has_provenance() is True
    assert r1._probe_has_mass_hiring() is True
    first_calls = client.select_calls
    assert first_calls == 3

    # New instance (same client URL) must hit module cache — zero new probes.
    r2 = jr.JobRepository(client=client)
    assert r2._probe_has_last_seen_at() is True
    assert r2._probe_has_provenance() is True
    assert r2._probe_has_mass_hiring() is True
    assert client.select_calls == first_calls

    jr.JobRepository.clear_probe_cache()


def test_clear_probe_cache_forces_reprobe():
    jr.JobRepository.clear_probe_cache()
    client = _FakeClient()
    r = jr.JobRepository(client=client)
    r._probe_has_last_seen_at()
    calls = client.select_calls
    jr.JobRepository.clear_probe_cache()
    r2 = jr.JobRepository(client=client)
    r2._probe_has_last_seen_at()
    assert client.select_calls > calls
    jr.JobRepository.clear_probe_cache()
