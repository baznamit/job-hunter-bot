from unittest.mock import patch

from models.company import Company
from src.providers.eightfold import (
    EightfoldAdapter,
)

def _company():
    return Company.model_validate(
        {
            "id": "microsoft",
            "name": "Microsoft",
            "category": "SaaS",
            "priority": 3,
            "career_page": (
                "https://apply.careers."
                "microsoft.com/careers"
            ),
            "provider": {
                "type": "eightfold",
                "status": "implemented",
                "config": {
                    "base_url": (
                        "https://apply.careers."
                        "microsoft.com"
                    ),
                    "domain":
                        "microsoft.com",
                },
            },
        }
    )

def test_eightfold_parses_position():
    adapter = EightfoldAdapter()

    raw = {
        "positions": [
            {
                "id":
                    1970393556960679,
                "displayJobId":
                    "200048252",
                "name": (
                    "Senior Software Engineer "
                    "- Data Platform"
                ),
                "locations": [
                    (
                        "India, Karnataka, "
                        "Bangalore"
                    ),
                    (
                        "India, Telangana, "
                        "Hyderabad"
                    ),
                ],
                "standardizedLocations": [
                    "Bengaluru, KA, IN",
                    "Hyderabad, TS, IN",
                ],
                "postedTs":
                    1786610951,
                "department":
                    "Software Engineering",
                "workLocationOption":
                    "onsite",
                "positionUrl": (
                    "/careers/job/"
                    "1970393556960679"
                ),
            }
        ]
    }

    jobs = adapter.parse(
        raw,
        _company(),
    )

    assert len(jobs) == 1

    job = jobs[0]

    assert (
        job.id
        == "1970393556960679"
    )

    assert job.title == (
        "Senior Software Engineer "
        "- Data Platform"
    )

    assert job.location == (
        "Bengaluru, KA, IN / "
        "Hyderabad, TS, IN"
    )

    assert job.department == (
        "Software Engineering"
    )

    assert job.posted_at is not None

    assert str(job.url) == (
        "https://apply.careers."
        "microsoft.com/careers/job/"
        "1970393556960679"
    )

def test_eightfold_remote_flag():
    adapter = EightfoldAdapter()

    raw = {
        "positions": [
            {
                "id": 123,
                "name": "Software Engineer",
                "standardizedLocations": [
                    "US"
                ],
                "workLocationOption":
                    "remote",
                "positionUrl":
                    "/careers/job/123",
            }
        ]
    }

    jobs = adapter.parse(
        raw,
        _company(),
    )

    assert len(jobs) == 1
    assert jobs[0].remote is True

class _Response:
    def __init__(
        self,
        payload,
    ):
        self._payload = payload
        self.status_code = 200
        self.url = (
            "https://apply.careers."
            "microsoft.com/api/pcsx/search"
        )
        self.headers = {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None

def _payload(
    start: int,
    total: int,
):
    positions = [
        {
            "id": start + index,
            "name":
                f"Software Engineer "
                f"{start + index}",
            "standardizedLocations": [
                "Bengaluru, KA, IN"
            ],
            "positionUrl": (
                f"/careers/job/"
                f"{start + index}"
            ),
        }
        for index in range(
            min(
                10,
                total - start,
            )
        )
    ]

    return {
        "status": 200,
        "data": {
            "positions": positions,
            "count": total,
        },
    }

def test_eightfold_fetches_all_pages():
    company = _company()

    def fake_get(
        url,
        *,
        params,
        headers,
        timeout,
    ):
        return _Response(
            _payload(
                params["start"],
                25,
            )
        )

    with patch(
        "src.providers.eightfold."
        "requests.get",
        side_effect=fake_get,
    ) as mock_get:
        raw = (
            EightfoldAdapter()
            ._fetch_raw(company)
        )

    assert len(
        raw["positions"]
    ) == 25

    starts = sorted(
        call.kwargs[
            "params"
        ]["start"]
        for call
        in mock_get.call_args_list
    )

    assert starts == [
        0,
        10,
        20,
    ]
