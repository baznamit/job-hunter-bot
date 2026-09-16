from unittest.mock import patch

from models.company import (
    Company,
    CompanyCategory,
    Provider,
    ProviderConfig,
    ProviderStatus,
    ProviderType,
)
from src.providers.bankofamerica import (
    BankOfAmericaAdapter,
)


def _company() -> Company:
    return Company(
        id="bank-of-america",
        name="Bank of America",
        category=CompanyCategory.BANKING,
        priority=1,
        career_page=(
            "https://careers."
            "bankofamerica.com/"
            "en-us/job-search/india"
        ),
        provider=Provider(
            type=(
                ProviderType
                .BANKOFAMERICA
            ),
            status=(
                ProviderStatus
                .VERIFIED
            ),
            config=ProviderConfig(
                base_url=(
                    "https://careers."
                    "bankofamerica.com"
                ),
            ),
        ),
    )


class _Response:
    def __init__(
        self,
        payload,
    ):
        self._payload = payload
        self.status_code = 200
        self.url = (
            "https://careers."
            "bankofamerica.com/"
            "services/jobssearchservlet"
        )
        self.headers = {
            "Content-Type":
                "application/json"
        }
        self.text = ""

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


def _job(
    job_id: int,
) -> dict:
    return {
        "jobRequisitionId":
            str(job_id),
        "postingTitle":
            f"Software Engineer {job_id}",
        "location":
            "Mumbai, India",
        "postedDate":
            "2026-09-16",
        "careerArea":
            "Technology",
        "externalUrl": (
            "/en-us/job-detail/"
            f"{job_id}/"
            f"software-engineer-{job_id}"
        ),
    }


def test_parses_json_job():
    adapter = (
        BankOfAmericaAdapter()
    )

    raw = {
        "jobsList": [
            {
                "jobRequisitionId":
                    "26029961",
                "postingTitle":
                    "Software Engineer III",
                "location":
                    "Mumbai, India",
                "postedDate":
                    "2026-09-16",
                "careerArea":
                    "Technology",
                "externalUrl": (
                    "/en-us/job-detail/"
                    "26029961/"
                    "software-engineer-iii"
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

    assert job.id == "26029961"

    assert (
        job.title
        == "Software Engineer III"
    )

    assert (
        job.location
        == "Mumbai, India"
    )

    assert (
        job.department
        == "Technology"
    )

    assert job.posted_at is not None

    assert str(job.url) == (
        "https://careers."
        "bankofamerica.com/"
        "en-us/job-detail/"
        "26029961/"
        "software-engineer-iii"
    )


def test_bofa_uses_end_pointer_pagination():
    adapter = (
        BankOfAmericaAdapter()
    )

    calls: list[
        tuple[int, int]
    ] = []

    def fake_get(
        url,
        *,
        params,
        headers,
        timeout,
    ):
        start = params["start"]
        rows = params["rows"]

        calls.append(
            (
                start,
                rows,
            )
        )

        pages = {
            (0, 10): [
                _job(i)
                for i
                in range(0, 10)
            ],
            (10, 20): [
                _job(i)
                for i
                in range(10, 20)
            ],
            (20, 25): [
                _job(i)
                for i
                in range(20, 25)
            ],
        }

        return _Response(
            {
                "jobsList":
                    pages[
                        (
                            start,
                            rows,
                        )
                    ],
                "totalMatches": 25,
            }
        )

    with patch(
        "src.providers."
        "bankofamerica."
        "requests.get",
        side_effect=fake_get,
    ):
        raw = adapter._fetch_raw(
            _company()
        )

    assert len(
        raw["jobsList"]
    ) == 25

    assert calls == [
        (0, 10),
        (10, 20),
        (20, 25),
    ]


def test_bofa_detects_repeated_page():
    adapter = (
        BankOfAmericaAdapter()
    )

    page = [
        _job(i)
        for i in range(
            10
        )
    ]

    def fake_get(
        url,
        *,
        params,
        headers,
        timeout,
    ):
        return _Response(
            {
                "jobsList": page,
                "totalMatches": 20,
            }
        )

    with patch(
        "src.providers."
        "bankofamerica."
        "requests.get",
        side_effect=fake_get,
    ):
        try:
            adapter._fetch_raw(
                _company()
            )

        except RuntimeError as exc:
            assert (
                "pagination stalled"
                in str(exc)
            )

        else:
            raise AssertionError(
                "Expected pagination "
                "stall RuntimeError"
            )


def test_bofa_request_contract():
    adapter = (
        BankOfAmericaAdapter()
    )

    with patch(
        "src.providers."
        "bankofamerica."
        "requests.get",
        return_value=_Response(
            {
                "jobsList": [],
                "totalMatches": 0,
            }
        ),
    ) as mock_get:
        adapter._request_page(
            _company(),
            start=10,
            rows=20,
        )

    params = (
        mock_get.call_args
        .kwargs["params"]
    )

    assert params == {
        "country": "India",
        "start": 10,
        "rows": 20,
        "search": "jobsByCountry",
    }
