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
from src.providers.workday import WorkdayAdapter
from src.providers.smartrecruiters import SmartRecruitersAdapter
from src.providers.oracle import OracleAdapter

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

# ── Workday ───────────────────────────────────────────────────────────────────

def test_workday_builds_public_job_url():
    company = _company(
        ProviderType.WORKDAY,
        tenant="visa",
        board="Visa",
        cluster="wd5",
    )

    raw = {
        "jobPostings": [
            {
                "title": "Software Engineer",
                "externalPath": "/job/Bangalore-IND/Software-Engineer_R123456",
                "locationsText": "Bangalore, India",
            }
        ]
    }

    jobs = WorkdayAdapter().parse(raw, company)

    assert len(jobs) == 1

    job = jobs[0]

    assert job.title == "Software Engineer"
    assert job.location == "Bangalore, India"
    assert str(job.url) == (
    "https://visa.wd5.myworkdayjobs.com/"
    "en-US/Visa/job/Bangalore-IND/Software-Engineer_R123456"
    )

def test_smartrecruiters_parses_job():
    company = _company(
        ProviderType.SMARTRECRUITERS,
        company_identifier="Canva",
    )

    raw = {
        "content": [
            {
                "id": "6000000001224319",
                "name": "Backend Engineer",
                "location": {
                    "city": "Bengaluru",
                    "region": "Karnataka",
                    "country": "India",
                },
                "department": {
                    "label": "Engineering",
                },
            }
        ]
    }

    jobs = SmartRecruitersAdapter().parse(
        raw,
        company,
    )

    assert len(jobs) == 1

    job = jobs[0]

    assert job.id == "6000000001224319"
    assert job.title == "Backend Engineer"
    assert job.location == "Bengaluru, Karnataka, India"
    assert job.department == "Engineering"
    assert str(job.url) == (
        "https://jobs.smartrecruiters.com/"
        "Canva/6000000001224319"
    )

def test_smartrecruiters_unknown_location():
    company = _company(
        ProviderType.SMARTRECRUITERS,
        company_identifier="Canva",
    )

    raw = {
        "content": [
            {
                "id": "123",
                "name": "Software Engineer",
                "location": {},
            }
        ]
    }

    job = SmartRecruitersAdapter().parse(
        raw,
        company,
    )[0]

    assert job.location == "Unknown"

def test_oracle_parses_job():
    company = _company(
        ProviderType.ORACLE,
        host="jpmc.fa.oraclecloud.com",
        sites=[
            {
                "site_number": "CX_1001",
                "site_path": "CX_1001",
            }
        ],
    )

    raw = {
        "requisitions": [
            {
                "job": {
                    "Id": "210756184",
                    "Title": "Software Engineer II - Java",
                    "PrimaryLocation":
                        "Mumbai, Maharashtra, India",
                    "PrimaryLocationCountry": "IN",
                    "PostedDate":
                        "2026-08-18T12:00:00+00:00",
                    "Department": "Technology",
                },
                "site_path": "CX_1001",
                "public_url_prefix": None,
            }
        ]
    }

    jobs = OracleAdapter().parse(
        raw,
        company,
    )

    assert len(jobs) == 1

    job = jobs[0]

    assert job.id == "210756184"
    assert job.title == (
        "Software Engineer II - Java"
    )
    assert job.location == (
        "Mumbai, Maharashtra, India"
    )
    assert job.department == "Technology"
    assert job.posted_at is not None

    assert str(job.url) == (
        "https://jpmc.fa.oraclecloud.com/"
        "hcmUI/CandidateExperience/en/sites/"
        "CX_1001/job/210756184"
    )

def test_oracle_site_path_is_independent_of_site_number():
    company = _company(
        ProviderType.ORACLE,
        host="eeho.fa.us2.oraclecloud.com",
        sites=[
            {
                "site_number": "CX_1",
                "site_path": "jobsearch",
            }
        ],
    )

    raw = {
        "requisitions": [
            {
                "job": {
                    "Id": "331738",
                    "Title": "Software Engineer",
                    "PrimaryLocation":
                        "Bengaluru, Karnataka, India",
                },
                "site_path": "jobsearch",
                "public_url_prefix": None,
            }
        ]
    }

    job = OracleAdapter().parse(
        raw,
        company,
    )[0]

    assert str(job.url) == (
        "https://eeho.fa.us2.oraclecloud.com/"
        "hcmUI/CandidateExperience/en/sites/"
        "jobsearch/job/331738"
    )

def test_oracle_supports_custom_public_url_prefix():
    company = _company(
        ProviderType.ORACLE,
        host="careers.americanexpress.com",
        sites=[
            {
                "site_number": "CX_1",
                "site_path": "CX_1",
                "public_url_prefix": (
                    "https://careers.americanexpress.com/"
                    "en/sites/CX_1/job/"
                ),
            }
        ],
    )

    raw = {
        "requisitions": [
            {
                "job": {
                    "Id": "26010639",
                    "Title": "Software Engineer III",
                    "PrimaryLocation":
                        "Bengaluru, Karnataka, India",
                },
                "site_path": "CX_1",
                "public_url_prefix": (
                    "https://careers.americanexpress.com/"
                    "en/sites/CX_1/job/"
                ),
            }
        ]
    }

    job = OracleAdapter().parse(
        raw,
        company,
    )[0]

    assert str(job.url) == (
        "https://careers.americanexpress.com/"
        "en/sites/CX_1/job/26010639"
    )