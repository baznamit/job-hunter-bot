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
            "id": 138159,
            "title": "Software Engineer",
            "departmentIdentifier": (
                "808a3e94-73d2-46d2-"
                "bcf8-8b477dd40b1e"
            ),
            "departmentName": "Engineering",
            "jobLocations": [
                {
                    "id": 31395,
                    "name": "Europa Bangalore",
                    "city": "Bengaluru",
                    "state": "KA",
                    "countryCode": "IN",
                    "countryName": "India",
                }
            ],
            "jobType": 2,
            "experience": "2-3",
            "publishedOn": (
                "2026-08-18T11:16:42.937Z"
            ),
            "publishedSinceDays": 21,
            "skillNames": [
                "Java",
                "Python",
            ],
        }
    ]

    jobs = adapter.parse(
        raw,
        _company(),
    )

    assert len(jobs) == 1

    job = jobs[0]

    assert job.id == "138159"
    assert (
        job.title
        == "Software Engineer"
    )
    assert (
        job.location
        == "Bengaluru, KA, India"
    )
    assert (
        job.department
        == "Engineering"
    )
    assert (
        job.employment_type
        == "2"
    )
    assert job.posted_at is not None


def test_keka_handles_multiple_locations():
    adapter = KekaAdapter()

    raw = [
        {
            "id": 123,
            "title": "Backend Engineer",
            "jobLocations": [
                {
                    "city": "Bengaluru",
                    "state": "KA",
                    "countryName": "India",
                },
                {
                    "city": "Mumbai",
                    "state": "MH",
                    "countryName": "India",
                },
            ],
            "jobType": 2,
        }
    ]

    jobs = adapter.parse(
        raw,
        _company(),
    )

    assert len(jobs) == 1

    assert jobs[0].location == (
        "Bengaluru, KA, India / "
        "Mumbai, MH, India"
    )
