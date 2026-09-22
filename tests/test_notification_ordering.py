from datetime import (
    datetime,
    timezone,
)

from models import Job
from src.main import (
    _sort_notification_jobs,
)


def _job(
    job_id: str,
    location: str,
    posted_at: datetime,
) -> Job:
    return Job(
        id=job_id,
        title="Software Engineer",
        company="Test Company",
        location=location,
        url=(
            f"https://example.com/"
            f"jobs/{job_id}"
        ),
        posted_at=posted_at,
    )


def test_notification_order_prioritizes_location():
    settings = {
        "locations": {
            "notification_priority": [
                {
                    "name": "Mumbai",
                    "terms": [
                        "Mumbai",
                        "Navi Mumbai",
                    ],
                },
                {
                    "name": "Bengaluru",
                    "terms": [
                        "Bangalore",
                        "Bengaluru",
                    ],
                },
            ]
        }
    }

    jobs = [
        _job(
            "india",
            "India",
            datetime(
                2026,
                9,
                22,
                tzinfo=timezone.utc,
            ),
        ),
        _job(
            "bengaluru",
            "Bengaluru, KA, IN",
            datetime(
                2026,
                9,
                22,
                tzinfo=timezone.utc,
            ),
        ),
        _job(
            "mumbai-old",
            "Mumbai, MH, IN",
            datetime(
                2026,
                9,
                20,
                tzinfo=timezone.utc,
            ),
        ),
        _job(
            "mumbai-new",
            "Navi Mumbai, Maharashtra, India",
            datetime(
                2026,
                9,
                21,
                tzinfo=timezone.utc,
            ),
        ),
    ]

    ordered = (
        _sort_notification_jobs(
            jobs,
            settings,
        )
    )

    assert [
        job.id
        for job in ordered
    ] == [
        "mumbai-new",
        "mumbai-old",
        "bengaluru",
        "india",
    ]
