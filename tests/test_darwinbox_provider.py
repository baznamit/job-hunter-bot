from models.company import Company
from src.providers.darwinbox import DarwinboxAdapter


def _company() -> Company:
    return Company.model_validate(
        {
            "id": "upstox",
            "name": "Upstox",
            "category": "FinTech",
            "priority": 1,
            "career_page": "https://upstox.com/careers/",
            "provider": {
                "type": "darwinbox",
                "status": "verified",
                "config": {
                    "api_url": "https://service.upstox.com/content/open/v1/jobs/"
                },
            },
        }
    )


def test_parses_public_darwinbox_job_and_normalizes_fields():
    raw = {
        "data": [
            {
                "job_id": "job-123",
                "job_title": "Software Engineer",
                "department": "Tech",
                "location_city": ["Mumbai", "Bangalore"],
                "employee_type": "Permanent",
                "job_created_timestamp": "25-11-2026 16:11:59",
                "post_on_careers_page": 1,
                "is_remote": 0,
            }
        ]
    }

    jobs = DarwinboxAdapter().parse(raw, _company())

    assert len(jobs) == 1
    assert jobs[0].id == "job-123"
    assert jobs[0].title == "Software Engineer"
    assert jobs[0].location == "Mumbai, Bangalore"
    assert jobs[0].department == "Tech"
    assert jobs[0].employment_type == "Permanent"
    assert jobs[0].posted_at.isoformat() == "2026-11-25T16:11:59"
    assert str(jobs[0].url).endswith("jobDetails/job-123?from=all")
    assert jobs[0].remote is False


def test_ignores_unpublished_and_incomplete_darwinbox_records():
    raw = {
        "data": [
            {
                "job_id": "not-public",
                "job_title": "Private Role",
                "post_on_careers_page": 0,
            },
            {
                "job_id": "missing-title",
                "post_on_careers_page": 1,
            },
        ]
    }

    assert DarwinboxAdapter().parse(raw, _company()) == []
