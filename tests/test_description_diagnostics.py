from unittest.mock import patch

from models import Job
from src.description_diagnostics import (
    _candidate_score,
    enrich_near_misses,
    find_signals,
    promotable_jobs,
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
    assert "spring boot" in signals
    assert "spring" not in signals
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

def test_software_development_engineer_outranks_generic_engineer():
    generic = _job(
        "Engineer II",
        "Bangalore",
    )

    software = _job(
        "Software Development Engineer 4",
        "Bangalore",
    )

    generic_score = _candidate_score(
        generic,
        RejectionReason.INCLUDE_KEYWORD,
    )

    software_score = _candidate_score(
        software,
        RejectionReason.INCLUDE_KEYWORD,
    )

    assert software_score > generic_score


def test_computer_scientist_outranks_generic_engineer():
    generic = _job(
        "Engineer",
        "Bangalore",
    )

    computer_scientist = _job(
        "Computer Scientist II",
        "Bangalore",
    )

    assert _candidate_score(
        computer_scientist,
        RejectionReason.INCLUDE_KEYWORD,
    ) > _candidate_score(
        generic,
        RejectionReason.INCLUDE_KEYWORD,
    )


def test_target_city_outranks_broad_india_location():
    bangalore = _job(
        "Computer Scientist II",
        "Bangalore",
    )

    india = _job(
        "Computer Scientist II",
        "India",
    )

    assert _candidate_score(
        bangalore,
        RejectionReason.INCLUDE_KEYWORD,
    ) > _candidate_score(
        india,
        RejectionReason.INCLUDE_KEYWORD,
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
    assert "spring" not in results[0].signals
    assert "backend" in results[0].signals
    assert "microservices" in results[0].signals
    assert "microservice" not in results[0].signals
    assert "kafka" in results[0].signals

@patch(
    "src.description_diagnostics.fetch_description_text"
)
def test_enrichment_limit_is_applied_after_ranking(
    mock_fetch,
):
    mock_fetch.return_value = (
        "Java Spring Boot backend microservices Kafka"
    )

    job_filter = JobFilter()

    jobs = [
        _job("Engineer", "Bangalore"),
        _job("Engineer II", "Bangalore"),
        _job("Computer Scientist II", "Bangalore"),
    ]

    results = enrich_near_misses(
        jobs,
        job_filter,
        limit=1,
    )

    assert len(results) == 1

    assert (
        results[0].job.title
        == "Computer Scientist II"
    )

def test_strong_include_miss_can_be_promoted():
    job_filter = JobFilter()

    job = _job(
        "Senior Engineer, Messaging Platform",
        "Bengaluru",
    )

    from src.description_diagnostics import EnrichedNearMiss

    item = EnrichedNearMiss(
        job=job,
        rejection_reason=RejectionReason.INCLUDE_KEYWORD,
        signals=[
            "java",
            "backend",
            "distributed systems",
        ],
        strong=True,
    )

    promoted = promotable_jobs(
        [item],
        job_filter,
    )

    assert promoted == [job]


def test_staff_role_is_not_promoted():
    job_filter = JobFilter()

    job = _job(
        "Staff Engineer, Core Infrastructure",
        "Bengaluru",
    )

    from src.description_diagnostics import EnrichedNearMiss

    item = EnrichedNearMiss(
        job=job,
        rejection_reason=RejectionReason.INCLUDE_KEYWORD,
        signals=[
            "backend",
            "distributed systems",
        ],
        strong=True,
    )

    promoted = promotable_jobs(
        [item],
        job_filter,
    )

    assert promoted == []


def test_foreign_remote_role_is_not_promoted():
    job_filter = JobFilter()

    job = _job(
        "Senior Engineer, Messaging Platform",
        "Remote - USA",
    )

    from src.description_diagnostics import EnrichedNearMiss

    item = EnrichedNearMiss(
        job=job,
        rejection_reason=RejectionReason.INCLUDE_KEYWORD,
        signals=[
            "java",
            "backend",
        ],
        strong=True,
    )

    promoted = promotable_jobs(
        [item],
        job_filter,
    )

    assert promoted == []