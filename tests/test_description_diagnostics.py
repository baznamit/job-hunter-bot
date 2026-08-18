from unittest.mock import patch

from models import Job
from src.description_diagnostics import (
    enrich_near_misses,
    find_signals,
    should_enrich,
)
from src.filters import JobFilter, RejectionReason


def _job(
    title: str,
    location: str = "Bengaluru",
) -> Job:
    return Job(
        id=title,
        title=title,
        company="Test Co",
        location=location,
        url="https://example.com/job",
    )


def test_finds_backend_signals():
    signals = find_signals(
        """
        Build backend services using Java, Spring Boot,
        Kafka and distributed systems.
        """
    )

    assert "java" in signals
    assert "spring" in signals
    assert "spring boot" in signals
    assert "backend" in signals
    assert "kafka" in signals
    assert "distributed systems" in signals


def test_ambiguous_engineer_is_enriched():
    job_filter = JobFilter()

    job = _job(
        "Computer Scientist II",
        "Bangalore",
    )

    assert should_enrich(
        job,
        RejectionReason.INCLUDE_KEYWORD,
        job_filter,
    )


def test_senior_software_engineer_is_enriched():
    job_filter = JobFilter()

    job = _job(
        "Senior Software Engineer",
        "Bengaluru",
    )

    assert should_enrich(
        job,
        RejectionReason.SENIORITY,
        job_filter,
    )


def test_engineering_manager_is_not_enriched():
    job_filter = JobFilter()

    job = _job(
        "Engineering Manager",
        "Bengaluru",
    )

    assert not should_enrich(
        job,
        RejectionReason.INCLUDE_KEYWORD,
        job_filter,
    )


def test_remote_usa_is_not_enriched():
    job_filter = JobFilter()

    job = _job(
        "Engineer II",
        "Remote - USA",
    )

    assert not should_enrich(
        job,
        RejectionReason.INCLUDE_KEYWORD,
        job_filter,
    )


def test_remote_india_is_enriched():
    job_filter = JobFilter()

    job = _job(
        "Engineer II",
        "Remote - India",
    )

    assert should_enrich(
        job,
        RejectionReason.INCLUDE_KEYWORD,
        job_filter,
    )


@patch(
    "src.description_diagnostics.fetch_description_text"
)
def test_strong_near_miss_is_detected(
    mock_fetch,
):
    mock_fetch.return_value = (
        "Java Spring Boot backend microservices Kafka"
    )

    job_filter = JobFilter()

    jobs = [
        _job(
            "Computer Scientist II",
            "Bangalore",
        )
    ]

    results = enrich_near_misses(
        jobs,
        job_filter,
    )

    assert len(results) == 1
    assert results[0].strong
    assert "java" in results[0].signals
    assert "spring boot" in results[0].signals