from models.company import Company
from src.providers.phonepe import PhonePeAdapter

def _company():
    return Company.model_validate(
        {
            "id": "phonepe",
            "name": "PhonePe",
            "category": "Payments",
            "priority": 1,
            "career_page": (
                "https://www.phonepe.com/"
                "careers/job-openings/"
            ),
            "provider": {
                "type": "phonepe",
                "status": "implemented",
                "config": {
                    "api_url": (
                        "https://www.phonepe.com/"
                        "apollo/job-postings/latest.json"
                    )
                },
            },
        }
    )

def test_phonepe_parses_public_job():
    adapter = PhonePeAdapter()

    raw = {
        "results": [
            {
                "id": "12345",
                "title": "Software Engineer",
                "location": "Bengaluru",
                "department": "Engineering",
                "type": "Full Time",
                "status": "PUBLIC",
                "applyUrl": (
                    "https://example.com/jobs/12345"
                ),
            }
        ]
    }

    jobs = adapter.parse(
        raw,
        _company(),
    )

    assert len(jobs) == 1
    assert jobs[0].id == "12345"
    assert jobs[0].title == "Software Engineer"
    assert jobs[0].location == "Bengaluru"
    assert jobs[0].department == "Engineering"

def test_phonepe_ignores_non_public_job():
    adapter = PhonePeAdapter()

    raw = {
        "results": [
            {
                "id": "12345",
                "title": "Software Engineer",
                "location": "Bengaluru",
                "status": "CLOSED",
                "applyUrl": (
                    "https://example.com/jobs/12345"
                ),
            }
        ]
    }

    jobs = adapter.parse(
        raw,
        _company(),
    )

    assert jobs == []
