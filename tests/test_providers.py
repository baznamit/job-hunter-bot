import json
from pathlib import Path
from unittest.mock import patch

import pytest

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
from src.providers.workday import (
    WorkdayAdapter,
    WorkdayRequestPolicy,
)
from src.providers.smartrecruiters import SmartRecruitersAdapter
from src.providers.oracle import OracleAdapter
from src.providers.higher import HigherAdapter

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


class _FakeResponse:
    def __init__(
        self,
        payload: dict,
        url: str = (
            "https://example.com/jobs"
        ),
    ):
        self._payload = payload
        self.url = url
        self.status_code = 200

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


def _workday_posting(
    number: int,
) -> dict:
    return {
        "title":
            f"Software Engineer {number}",
        "externalPath":
            f"/job/Test/Engineer_R{number}",
        "locationsText":
            "Mumbai, India",
    }


def test_workday_parallel_pagination_fetches_all_pages():
    company = _company(
        ProviderType.WORKDAY,
        tenant="test",
        board="Careers",
        cluster="wd1",
    )

    def fake_post(
        url,
        *,
        json,
        headers,
        timeout,
    ):
        offset = json["offset"]

        if offset == 0:
            payload = {
                "total": 45,
                "jobPostings": [
                    _workday_posting(i)
                    for i in range(
                        0,
                        20,
                    )
                ],
            }

        elif offset == 20:
            payload = {
                "total": 0,
                "jobPostings": [
                    _workday_posting(i)
                    for i in range(
                        20,
                        40,
                    )
                ],
            }

        elif offset == 40:
            payload = {
                "total": 0,
                "jobPostings": [
                    _workday_posting(i)
                    for i in range(
                        40,
                        45,
                    )
                ],
            }

        else:
            raise AssertionError(
                f"unexpected offset {offset}"
            )

        return _FakeResponse(
            payload,
            url,
        )

    with patch(
        "src.providers.workday.requests.post",
        side_effect=fake_post,
    ) as mock_post:
        raw = WorkdayAdapter()._fetch_raw(
            company
        )

    postings = raw[
        "jobPostings"
    ]

    assert len(postings) == 45

    assert [
        item["externalPath"]
        for item in postings
    ] == [
        (
            f"/job/Test/"
            f"Engineer_R{i}"
        )
        for i in range(45)
    ]

    offsets = sorted(
        call.kwargs["json"]["offset"]
        for call in mock_post.call_args_list
    )

    assert offsets == [
        0,
        20,
        40,
    ]


def test_workday_parallel_pagination_deduplicates_jobs():
    company = _company(
        ProviderType.WORKDAY,
        tenant="test",
        board="Careers",
        cluster="wd1",
    )

    duplicate = (
        _workday_posting(19)
    )

    def fake_post(
        url,
        *,
        json,
        headers,
        timeout,
    ):
        offset = json["offset"]

        if offset == 0:
            return _FakeResponse(
                {
                    "total": 21,
                    "jobPostings": [
                        _workday_posting(i)
                        for i in range(20)
                    ],
                },
                url,
            )

        return _FakeResponse(
            {
                "total": 0,
                "jobPostings": [
                    duplicate,
                    _workday_posting(20),
                ],
            },
            url,
        )

    with patch(
        "src.providers.workday.requests.post",
        side_effect=fake_post,
    ):
        raw = WorkdayAdapter()._fetch_raw(
            company
        )

    paths = [
        item["externalPath"]
        for item in raw[
            "jobPostings"
        ]
    ]

    assert len(paths) == 21
    assert len(set(paths)) == 21


def test_workday_missing_total_uses_sequential_fallback():
    company = _company(
        ProviderType.WORKDAY,
        tenant="test",
        board="Careers",
        cluster="wd1",
    )

    def fake_post(
        url,
        *,
        json,
        headers,
        timeout,
    ):
        offset = json["offset"]

        if offset == 0:
            return _FakeResponse(
                {
                    "jobPostings": [
                        _workday_posting(i)
                        for i in range(20)
                    ],
                },
                url,
            )

        if offset == 20:
            return _FakeResponse(
                {
                    "jobPostings": [
                        _workday_posting(20)
                    ],
                },
                url,
            )

        if offset == 21:
            return _FakeResponse(
                {
                    "jobPostings": [],
                },
                url,
            )

        raise AssertionError(
            f"unexpected offset {offset}"
        )

    with patch(
        "src.providers.workday.requests.post",
        side_effect=fake_post,
    ) as mock_post:
        raw = WorkdayAdapter()._fetch_raw(
            company
        )

    assert len(
        raw["jobPostings"]
    ) == 21

    assert [
        call.kwargs["json"]["offset"]
        for call in mock_post.call_args_list
    ] == [
        0,
        20,
        21,
    ]


def test_workday_empty_first_page_with_zero_total_is_valid():
    company = _company(
        ProviderType.WORKDAY,
        tenant="test",
        board="Careers",
        cluster="wd1",
    )
    adapter = WorkdayAdapter(
        WorkdayRequestPolicy(pacing_seconds=0)
    )

    with patch.object(
        adapter,
        "_request_page",
        return_value={"jobPostings": [], "total": 0},
    ):
        raw = adapter._fetch_raw(company)

    assert raw["jobPostings"] == []


@pytest.mark.parametrize(
    "total",
    [None, True, False, -1, "1", 1.0],
)
def test_workday_rejects_invalid_authoritative_totals(total):
    company = _company(
        ProviderType.WORKDAY,
        tenant="test",
        board="Careers",
        cluster="wd1",
    )
    adapter = WorkdayAdapter(
        WorkdayRequestPolicy(pacing_seconds=0)
    )

    with patch.object(
        adapter,
        "_request_page",
        return_value={"jobPostings": [], "total": total},
    ):
        with pytest.raises(ValueError, match="category=invalid_total"):
            adapter._fetch_raw(company)


def test_workday_empty_page_without_total_is_not_assumed_empty_inventory():
    company = _company(
        ProviderType.WORKDAY,
        tenant="test",
        board="Careers",
        cluster="wd1",
    )
    adapter = WorkdayAdapter(
        WorkdayRequestPolicy(pacing_seconds=0)
    )

    with patch.object(
        adapter,
        "_request_page",
        return_value={"jobPostings": []},
    ):
        with pytest.raises(
            ValueError,
            match="category=missing_total_for_empty_inventory",
        ):
            adapter._fetch_raw(company)


def test_workday_positive_total_with_empty_first_page_is_contradictory():
    company = _company(
        ProviderType.WORKDAY,
        tenant="test",
        board="Careers",
        cluster="wd1",
    )
    adapter = WorkdayAdapter(
        WorkdayRequestPolicy(pacing_seconds=0)
    )

    with patch.object(
        adapter,
        "_request_page",
        return_value={"jobPostings": [], "total": 2},
    ):
        with pytest.raises(
            ValueError,
            match="category=empty_page_with_positive_total",
        ):
            adapter._fetch_raw(company)


def test_workday_does_not_truncate_first_page_when_total_is_smaller():
    company = _company(
        ProviderType.WORKDAY,
        tenant="test",
        board="Careers",
        cluster="wd1",
    )
    adapter = WorkdayAdapter(
        WorkdayRequestPolicy(pacing_seconds=0)
    )

    with patch.object(
        adapter,
        "_request_page",
        return_value={
            "jobPostings": [
                _workday_posting(1),
                _workday_posting(2),
            ],
            "total": 1,
        },
    ):
        with pytest.raises(
            ValueError,
            match="category=total_smaller_than_first_page",
        ):
            adapter._fetch_raw(company)


def test_workday_rejects_underfilled_first_page_with_remaining_total():
    company = _company(
        ProviderType.WORKDAY,
        tenant="test",
        board="Careers",
        cluster="wd1",
    )
    adapter = WorkdayAdapter(
        WorkdayRequestPolicy(pacing_seconds=0)
    )

    with patch.object(
        adapter,
        "_request_page",
        return_value={
            "jobPostings": [_workday_posting(1)],
            "total": 21,
        },
    ):
        with pytest.raises(
            ValueError,
            match="category=short_first_page",
        ):
            adapter._fetch_raw(company)


def test_workday_rejects_empty_later_page_before_authoritative_total():
    company = _company(
        ProviderType.WORKDAY,
        tenant="test",
        board="Careers",
        cluster="wd1",
    )
    adapter = WorkdayAdapter(
        WorkdayRequestPolicy(pacing_seconds=0)
    )

    def fake_page(*, offset, **_kwargs):
        if offset == 0:
            return {
                "jobPostings": [
                    _workday_posting(index)
                    for index in range(20)
                ],
                "total": 45,
            }
        return {"jobPostings": [], "total": 45}

    with patch.object(adapter, "_request_page", side_effect=fake_page):
        with pytest.raises(
            ValueError,
            match=r"category=unexpected_empty_page.*offset=",
        ):
            adapter._fetch_raw(company)


def test_workday_rejects_short_later_page_before_authoritative_total():
    company = _company(
        ProviderType.WORKDAY,
        tenant="test",
        board="Careers",
        cluster="wd1",
    )
    adapter = WorkdayAdapter(
        WorkdayRequestPolicy(pacing_seconds=0)
    )

    def fake_page(*, offset, **_kwargs):
        if offset == 0:
            return {
                "jobPostings": [
                    _workday_posting(index)
                    for index in range(20)
                ],
                "total": 45,
            }
        if offset == 20:
            return {"jobPostings": [_workday_posting(20)]}
        return {
            "jobPostings": [
                _workday_posting(index)
                for index in range(40, 45)
            ]
        }

    with patch.object(adapter, "_request_page", side_effect=fake_page):
        with pytest.raises(ValueError, match="category=short_page"):
            adapter._fetch_raw(company)


def test_workday_sequential_fallback_rejects_repeated_pages():
    company = _company(
        ProviderType.WORKDAY,
        tenant="test",
        board="Careers",
        cluster="wd1",
    )
    adapter = WorkdayAdapter(
        WorkdayRequestPolicy(pacing_seconds=0)
    )
    first_page = [
        _workday_posting(index)
        for index in range(20)
    ]

    def fake_page(*, offset, **_kwargs):
        if offset == 0:
            return {"jobPostings": first_page}
        return {"jobPostings": first_page}

    with patch.object(adapter, "_request_page", side_effect=fake_page):
        with pytest.raises(
            ValueError,
            match="category=repeated_page",
        ):
            adapter._fetch_raw(company)


def test_workday_sequential_fallback_keeps_progress_with_duplicates():
    company = _company(
        ProviderType.WORKDAY,
        tenant="test",
        board="Careers",
        cluster="wd1",
    )
    adapter = WorkdayAdapter(
        WorkdayRequestPolicy(pacing_seconds=0)
    )
    first_page = [
        _workday_posting(index)
        for index in range(20)
    ]

    def fake_page(*, offset, **_kwargs):
        if offset == 0:
            return {"jobPostings": first_page}
        if offset == 20:
            return {
                "jobPostings": [
                    first_page[-1],
                    _workday_posting(20),
                ]
            }
        return {"jobPostings": []}

    with patch.object(adapter, "_request_page", side_effect=fake_page) as request:
        raw = adapter._fetch_raw(company)

    assert len(raw["jobPostings"]) == 21
    assert [
        call.kwargs["offset"]
        for call in request.call_args_list
    ] == [0, 20, 22]


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

def test_higher_parses_goldman_job():
    company = _company(
        ProviderType.HIGHER,
        graphql_url=(
            "https://api-higher.gs.com/"
            "gateway/api/v1/graphql"
        ),
        public_base_url="https://higher.gs.com",
    )

    raw = {
        "items": [
            {
                "roleId": "175255_GS_MID_CAREER",
                "corporateTitle": "Associate",
                "jobTitle": (
                    "Corporate Treasury - Liquidity "
                    "Management - Associate - Bengaluru"
                ),
                "jobFunction": "Liquidity Execution",
                "locations": [
                    {
                        "primary": True,
                        "state": "Karnataka",
                        "country": "India",
                        "city": "Bengaluru",
                    }
                ],
                "status": "POSTED",
                "division": "Corporate Treasury",
                "skills": [],
                "externalSource": {
                    "sourceId": "175255",
                },
            }
        ],
        "total": 1,
    }

    jobs = HigherAdapter().parse(
        raw,
        company,
    )

    assert len(jobs) == 1

    job = jobs[0]

    assert job.id == "175255_GS_MID_CAREER"
    assert job.location == (
        "Bengaluru, Karnataka, India"
    )
    assert job.department == "Corporate Treasury"

    assert str(job.url) == (
        "https://higher.gs.com/roles/175255"
    )

def test_higher_uses_external_source_for_public_url():
    company = _company(
        ProviderType.HIGHER,
        graphql_url="https://api-higher.gs.com/graphql",
        public_base_url="https://higher.gs.com",
    )

    raw = {
        "items": [
            {
                "roleId": "168761_GS_MID_CAREER",
                "jobTitle": "Data Engineering",
                "locations": [],
                "externalSource": {
                    "sourceId": "168761",
                },
            }
        ]
    }

    job = HigherAdapter().parse(
        raw,
        company,
    )[0]

    assert job.id == "168761_GS_MID_CAREER"

    assert str(job.url) == (
        "https://higher.gs.com/roles/168761"
    )