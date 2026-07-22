import json
from pathlib import Path

from models import Job
from models.company import (
    Company,
    CompanyCategory,
    Provider,
    ProviderConfig,
    ProviderStatus,
    ProviderType,
)
from src.providers.greenhouse import GreenhouseAdapter
from src.providers.lever import LeverAdapter
from src.providers.ashby import AshbyAdapter

FIXTURES = Path(__file__).parent / "fixtures"


def _company(provider_type: ProviderType, **config) -> Company:
    return Company(
        id="test",
        name="Test Co",
        category=CompanyCategory.SAAS,
        priority=1,
        career_page="https://example.com/careers",
        provider=Provider(
            type=provider_type,
            status=ProviderStatus.PARTIAL,
            config=ProviderConfig(**config),
        ),
    )


# ── Greenhouse ────────────────────────────────────────────────────────────────

def test_greenhouse_parses_valid_jobs():
    raw = json.loads((FIXTURES / "greenhouse_response.json").read_text())
    company = _company(ProviderType.GREENHOUSE, board="postman")
    jobs = GreenhouseAdapter().parse(raw, company)

    # Third item has null absolute_url and should be silently skipped.
    assert len(jobs) == 2
    assert all(isinstance(j, Job) for j in jobs)


def test_greenhouse_job_fields():
    raw = json.loads((FIXTURES / "greenhouse_response.json").read_text())
    company = _company(ProviderType.GREENHOUSE, board="postman")
    job = GreenhouseAdapter().parse(raw, company)[0]

    assert job.id == "7865432"
    assert job.title == "Software Engineer - Backend"
    assert job.company == "Test Co"
    assert job.location == "Bangalore, India"
    assert job.department == "Engineering"
    assert job.posted_at is not None


def test_greenhouse_null_location_defaults_to_unknown():
    raw = json.loads((FIXTURES / "greenhouse_response.json").read_text())
    company = _company(ProviderType.GREENHOUSE, board="postman")
    jobs = GreenhouseAdapter().parse(raw, company)
    remote_job = jobs[1]

    assert remote_job.location == "Remote"


# ── Lever ─────────────────────────────────────────────────────────────────────

def test_lever_parses_valid_jobs():
    raw = json.loads((FIXTURES / "lever_response.json").read_text())
    company = _company(ProviderType.LEVER, board="atlassian")
    jobs = LeverAdapter().parse(raw, company)

    assert len(jobs) == 2
    assert all(isinstance(j, Job) for j in jobs)


def test_lever_job_fields():
    raw = json.loads((FIXTURES / "lever_response.json").read_text())
    company = _company(ProviderType.LEVER, board="atlassian")
    job = LeverAdapter().parse(raw, company)[0]

    assert job.id == "abc-123-def-456"
    assert job.title == "Backend Engineer"
    assert job.company == "Test Co"
    assert job.location == "Bengaluru, India"
    assert job.department == "Engineering"
    assert job.remote is False
    assert job.posted_at is not None


def test_lever_empty_location_falls_back_to_remote():
    raw = json.loads((FIXTURES / "lever_response.json").read_text())
    company = _company(ProviderType.LEVER, board="atlassian")
    remote_job = LeverAdapter().parse(raw, company)[1]

    assert remote_job.location == "Remote"
    assert remote_job.remote is True


# ── Ashby ─────────────────────────────────────────────────────────────────────

def test_ashby_parses_valid_jobs():
    raw = json.loads((FIXTURES / "ashby_response.json").read_text())
    company = _company(ProviderType.ASHBY, organization="navi")
    jobs = AshbyAdapter().parse(raw, company)

    assert len(jobs) == 2
    assert all(isinstance(j, Job) for j in jobs)


def test_ashby_job_fields():
    raw = json.loads((FIXTURES / "ashby_response.json").read_text())
    company = _company(ProviderType.ASHBY, organization="navi")
    job = AshbyAdapter().parse(raw, company)[0]

    assert job.id == "xyz-456-abc"
    assert job.title == "Software Engineer"
    assert job.company == "Test Co"
    assert job.location == "Bengaluru, Karnataka, India"
    assert job.department == "Technology"
    assert job.remote is False
    assert job.posted_at is not None


def test_ashby_null_location_defaults_to_unknown():
    raw = json.loads((FIXTURES / "ashby_response.json").read_text())
    company = _company(ProviderType.ASHBY, organization="navi")
    jobs = AshbyAdapter().parse(raw, company)
    remote_job = jobs[1]

    assert remote_job.location == "Unknown"
    assert remote_job.remote is True
