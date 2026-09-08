from models.company import Company
from src.providers.keka import KekaAdapter

def _company():
    return Company.model_validate(
        {
            "id": "jupiter",
            "name": "Jupiter",
            "category": "FinTech",
            "priority": 3,
            "career_page": (
                "https://jupiter.money/careers/"
            ),
            "provider": {
                "type": "keka",
                "status": "implemented",
                "config": {
                    "base_url": (
                        "https://jupiter.keka.com/careers"
                    ),
                    "portal_name": "default",
                    "identifier": (
                        "b5279857-cf81-4dde-"
                        "a215-fc48957ee2b5"
                    ),
                },
            },
        }
    )

def test_keka_parses_job():
    adapter = KekaAdapter()

    raw = [
        {
            "identifier": "abc123",
            "jobNumber": "JUP-123",
            "title": "Software Engineer",
            "department": "Engineering",
            "jobType": "Full Time",
            "jobLocations": [
                {
                    "city": "Mumbai",
                    "stateName": "Maharashtra",
                    "countryName": "India",
                }
            ],
            "applyUrl": (
                "https://jupiter.keka.com/"
                "careers/job/abc123"
            ),
        }
    ]

    jobs = adapter.parse(
        raw,
        _company(),
    )

    assert len(jobs) == 1
    assert jobs[0].id == "abc123"
    assert jobs[0].title == "Software Engineer"
    assert (
        jobs[0].location
        == "Mumbai, Maharashtra, India"
    )
    assert jobs[0].department == "Engineering"
