import json
from pathlib import Path

import pytest
import requests
from unittest.mock import Mock, patch

from models.company import Company
from src.filters import JobFilter
from src.main import _run_company, _send_notifications, _settings
from src.providers.exceptions import ProviderTemporaryError
from src.providers.hcltech import HCLTechAdapter
from src.providers.ibm import IBMAdapter
from src.recovery_store import RecoveryStore
from src.store import SeenStore


def company(provider):
    return Company.model_validate({
        "id": provider,
        "name": provider.upper(),
        "category": "Product",
        "priority": 2,
        "career_page": (
            "https://careers.hcltech.com/search/"
            if provider == "hcltech"
            else "https://www.ibm.com/careers/search"
        ),
        "provider": {
            "type": provider,
            "status": "verified",
            "config": {},
        },
    })


def _hcl_response(records, total):
    response = Mock()
    response.status_code = 200
    response.url = (
        "https://careers.hcltech.com"
        "/services/recruiting/v1/jobs"
    )
    response.headers = {
        "Content-Type": "application/json"
    }
    response.json.return_value = {
        "totalJobs": total,
        "jobSearchResult": records,
    }
    response.raise_for_status = Mock()
    return response


def _ibm_response(records, total):
    response = Mock()
    response.status_code = 200
    response.url = "https://www-api.ibm.com/search/api/v2"
    response.headers = {"Content-Type": "application/json"}
    response.json.return_value = {
        "hits": {
            "total": {"value": total, "relation": "eq"},
            "hits": records,
        }
    }
    response.raise_for_status = Mock()
    return response


@pytest.mark.parametrize(
    ("provider", "adapter", "tag"),
    [
        ("ibm", IBMAdapter, "[IBM]"),
        ("hcltech", HCLTechAdapter, "[HCLTECH]"),
    ],
)
def test_pagination_summary_counts_overlapping_records(
    provider, adapter, tag, capsys,
):
    def record(number):
        if provider == "ibm":
            return {"_source": {
                "url": f"https://careers.ibm.com/careers/JobDetail?jobId={number}",
                "title": "Engineer",
            }}
        return {"response": {"id": str(number), "unifiedStandardTitle": "Engineer"}}

    response = _ibm_response if provider == "ibm" else _hcl_response
    session = Mock()
    session.post.side_effect = [
        response([record(1), record(2)], 4),
        response([record(2), record(3)], 4),
    ]
    test_company = company(provider)
    test_company.provider.config.search_terms = ["Java"]
    test_company.provider.config.page_size = 2
    test_company.provider.config.max_pages = 2

    with patch("requests.Session") as factory:
        factory.return_value.__enter__.return_value = session
        jobs = adapter().fetch_jobs(test_company)

    assert [job.id for job in jobs] == ["1", "2", "3"]
    assert session.post.call_count == 2
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1
    assert tag in lines[0]
    assert "terms=1 status=complete pages=2" in lines[0]
    assert "raw_records=4 processed_records=4" in lines[0]
    assert "total=4 unique=3 duplicates=1" in lines[0]


@pytest.mark.parametrize(
    ("provider", "adapter"),
    [("ibm", IBMAdapter), ("hcltech", HCLTechAdapter)],
)
def test_pagination_failure_keeps_progress_and_propagates(
    provider, adapter, capsys,
):
    if provider == "ibm":
        record = {"_source": {
            "url": "https://careers.ibm.com/careers/JobDetail?jobId=1",
            "title": "Engineer",
        }}
        first_response = _ibm_response([record], 2)
    else:
        record = {"response": {"id": "1", "unifiedStandardTitle": "Engineer"}}
        first_response = _hcl_response([record], 2)

    session = Mock()
    session.post.side_effect = [first_response, requests.ConnectionError("offline")]
    test_company = company(provider)
    test_company.provider.config.search_terms = ["Java"]
    test_company.provider.config.max_pages = 2

    with patch("requests.Session") as factory:
        factory.return_value.__enter__.return_value = session
        with pytest.raises(requests.ConnectionError, match="offline"):
            adapter().fetch_jobs(test_company)

    assert session.post.call_count == 2
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1
    assert "term='Java' status=failed pages=1" in lines[0]
    assert "raw_records=1 processed_records=1" in lines[0]
    assert "total=2 unique=1 duplicates=0" in lines[0]


@pytest.mark.parametrize(
    ("provider", "adapter"),
    [("ibm", IBMAdapter), ("hcltech", HCLTechAdapter)],
)
def test_failure_diagnostic_cannot_mask_original_error(provider, adapter):
    test_company = company(provider)
    test_company.provider.config.search_terms = ["Java"]

    with (
        patch("requests.Session") as factory,
        patch("builtins.print", side_effect=OSError("closed")),
    ):
        factory.return_value.__enter__.return_value.post.side_effect = (
            requests.ConnectionError("offline")
        )
        with pytest.raises(
            requests.ConnectionError,
            match="offline",
        ):
            adapter().fetch_jobs(test_company)


@pytest.mark.parametrize(
    ("provider", "adapter"),
    [("ibm", IBMAdapter), ("hcltech", HCLTechAdapter)],
)
def test_later_failure_keeps_completed_and_failed_term_summaries(
    provider,
    adapter,
    capsys,
):
    if provider == "ibm":
        complete = _ibm_response(
            [
                {
                    "_source": {
                        "url": (
                            "https://careers.ibm.com/careers/"
                            "JobDetail?jobId=1"
                        ),
                        "title": "Engineer",
                    }
                }
            ],
            1,
        )
    else:
        complete = _hcl_response(
            [
                {
                    "response": {
                        "id": "1",
                        "unifiedStandardTitle": "Engineer",
                    }
                }
            ],
            1,
        )

    session = Mock()
    session.post.side_effect = [
        complete,
        requests.ConnectionError("offline"),
    ]
    test_company = company(provider)
    test_company.provider.config.search_terms = [
        "Java",
        "Backend",
    ]

    with patch("requests.Session") as factory:
        factory.return_value.__enter__.return_value = session
        with pytest.raises(
            requests.ConnectionError,
            match="offline",
        ):
            adapter().fetch_jobs(test_company)

    output = capsys.readouterr().out
    assert "status=complete_before_failure" in output
    assert "term='Backend' status=failed" in output


@pytest.mark.parametrize(
    ("provider", "adapter"),
    [("ibm", IBMAdapter), ("hcltech", HCLTechAdapter)],
)
def test_incomplete_pagination_keeps_failure_summary(provider, adapter, capsys):
    if provider == "ibm":
        record = {"_source": {
            "url": "https://careers.ibm.com/careers/JobDetail?jobId=1",
            "title": "Engineer",
        }}
        response = _ibm_response([record], 2)
    else:
        record = {"response": {"id": "1", "unifiedStandardTitle": "Engineer"}}
        response = _hcl_response([record], 2)
    test_company = company(provider)
    test_company.provider.config.search_terms = ["Java"]
    test_company.provider.config.max_pages = 1

    with patch("requests.Session") as factory:
        factory.return_value.__enter__.return_value.post.return_value = response
        with pytest.raises(RuntimeError, match="incomplete"):
            adapter().fetch_jobs(test_company)

    output = capsys.readouterr().out
    assert "status=failed pages=1 raw_records=1 processed_records=1" in output
    assert "total=2 unique=1 duplicates=0" in output


@pytest.mark.parametrize(
    ("provider", "adapter"),
    [("ibm", IBMAdapter), ("hcltech", HCLTechAdapter)],
)
def test_rate_limit_failure_keeps_classification_and_summary(provider, adapter, capsys):
    response = Mock(status_code=429, url="https://example.com/search")
    response.headers = {"Retry-After": "3"}
    test_company = company(provider)
    test_company.provider.config.search_terms = ["Java"]

    with patch("requests.Session") as factory:
        factory.return_value.__enter__.return_value.post.return_value = response
        with pytest.raises(ProviderTemporaryError) as error:
            adapter().fetch_jobs(test_company)

    assert error.value.status == 429
    assert error.value.category == "rate_limit"
    assert error.value.retry_after_seconds == 3
    output = capsys.readouterr().out
    assert "status=failed pages=1 raw_records=0 processed_records=0" in output
    assert "total=None unique=0 duplicates=0" in output


def test_hcl_payload():
    payload = HCLTechAdapter._payload(
        1, "java"
    )

    assert payload["pageNumber"] == 1
    assert payload["keywords"] == "java"
    assert payload["locale"] == "en_US"


def test_hcl_parse():
    raw = [{
        "id": "178931",
        "unifiedStandardTitle": "Administrator - Java",
        "custprimecity": "Pune",
        "custCountryRegion": ["India"],
        "unifiedUrlTitle": "Administrator-Java",
        "unifiedStandardStart": "10/9/26",
    }]

    jobs = HCLTechAdapter().parse(
        raw, company("hcltech")
    )

    assert len(jobs) == 1
    assert jobs[0].id == "178931"
    assert jobs[0].title == "Administrator - Java"
    assert jobs[0].location == "Pune, India"
    assert str(jobs[0].url) == (
        "https://careers.hcltech.com/job/"
        "Administrator-Java/178931/"
    )
    assert jobs[0].posted_at.year == 2026


def test_hcl_deduplication():
    item = {
        "id": "178931",
        "unifiedStandardTitle": "Administrator - Java",
        "custprimecity": "Pune",
    }

    jobs = HCLTechAdapter().parse(
        [item, item], company("hcltech")
    )

    assert len(jobs) == 1


@patch("src.providers.hcltech.requests.Session")
def test_hcltech_deduplicates_across_search_terms(mock_session, capsys):
    item = {
        "response": {
            "id": "178931",
            "unifiedStandardTitle": "Administrator - Java",
            "custprimecity": "Mumbai",
            "custCountryRegion": ["India"],
            "unifiedUrlTitle": "Administrator-Java",
        }
    }
    session = Mock()
    session.post.side_effect = [
        _hcl_response([item], 1),
        _hcl_response([item], 1),
    ]
    mock_session.return_value.__enter__.return_value = session

    test_company = company("hcltech")
    test_company.provider.config.search_terms = [
        "Mumbai",
        "Bangalore",
    ]
    test_company.provider.config.max_pages = 1

    jobs = HCLTechAdapter().fetch_jobs(test_company)

    assert [job.id for job in jobs] == ["178931"]
    assert str(jobs[0].url) == (
        "https://careers.hcltech.com/job/"
        "Administrator-Java/178931/"
    )
    assert [
        call.kwargs["json"]["keywords"]
        for call in session.post.call_args_list
    ] == ["Mumbai", "Bangalore"]
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1
    assert "terms=2 status=complete pages=2" in lines[0]


@patch("src.providers.hcltech.requests.Session")
def test_hcltech_zero_results_without_job_list(mock_session, capsys):
    response = Mock()
    response.status_code = 200
    response.url = (
        "https://careers.hcltech.com"
        "/services/recruiting/v1/jobs"
    )
    response.headers = {
        "Content-Type": "application/json"
    }
    response.json.return_value = {
        "totalJobs": 0
    }
    response.raise_for_status = Mock()

    session = Mock()
    session.post.return_value = response
    mock_session.return_value.__enter__.return_value = session

    test_company = company("hcltech")
    test_company.provider.config.search_terms = ["Mumbai"]
    test_company.provider.config.max_pages = 1

    jobs = HCLTechAdapter().fetch_jobs(test_company)

    assert jobs == []
    assert (
        "terms=1 status=complete pages=1 "
        "raw_records=0 processed_records=0 "
        "total=0 unique=0 duplicates=0"
    ) in capsys.readouterr().out


@patch("src.providers.hcltech.requests.Session")
def test_hcltech_rejects_missing_positive_job_list(mock_session, capsys):
    response = Mock()
    response.status_code = 200
    response.url = (
        "https://careers.hcltech.com"
        "/services/recruiting/v1/jobs"
    )
    response.headers = {
        "Content-Type": "application/json"
    }
    response.json.return_value = {
        "totalJobs": 13,
        "description": "sensitive job description",
    }
    response.raise_for_status = Mock()

    session = Mock()
    session.post.return_value = response
    mock_session.return_value.__enter__.return_value = session

    test_company = company("hcltech")
    test_company.provider.config.search_terms = ["Mumbai"]
    test_company.provider.config.max_pages = 1

    with pytest.raises(
        RuntimeError,
        match="invalid jobSearchResult",
    ) as error:
        HCLTechAdapter().fetch_jobs(test_company)

    assert "sensitive job description" not in str(error.value)
    assert "sensitive job description" not in capsys.readouterr().out


@patch("src.providers.hcltech.requests.Session")
def test_hcltech_invalid_total_does_not_log_response_value(mock_session, capsys):
    response = _hcl_response([], "sensitive job description")
    mock_session.return_value.__enter__.return_value.post.return_value = response
    test_company = company("hcltech")
    test_company.provider.config.search_terms = ["Mumbai"]

    with pytest.raises(RuntimeError, match="invalid totalJobs") as error:
        HCLTechAdapter().fetch_jobs(test_company)

    assert "value_type=str" in str(error.value)
    assert "sensitive job description" not in str(error.value)
    assert "sensitive job description" not in capsys.readouterr().out


@patch("src.providers.hcltech.requests.Session")
def test_hcltech_fetches_more_than_300_jobs(mock_session):
    responses = []

    for page in range(32):
        page_size = 6 if page == 31 else 10
        records = [
            {
                "response": {
                    "id": f"hcl-{page * 10 + index}",
                    "unifiedStandardTitle": "Engineer",
                }
            }
            for index in range(page_size)
        ]
        response = Mock()
        response.status_code = 200
        response.headers = {
            "Content-Type": "application/json"
        }
        response.json.return_value = {
            "totalJobs": 316,
            "jobSearchResult": records,
        }
        response.raise_for_status = Mock()
        responses.append(response)

    session = Mock()
    session.post.side_effect = responses
    mock_session.return_value.__enter__.return_value = session

    test_company = company("hcltech")
    test_company.provider.config.search_terms = ["Mumbai"]
    test_company.provider.config.max_pages = 40

    jobs = HCLTechAdapter().fetch_jobs(test_company)

    assert len(jobs) == 316
    assert session.post.call_count == 32


@patch("src.providers.hcltech.requests.Session")
def test_hcltech_rejects_repeated_page_within_search_term(
    mock_session, capsys,
):
    records = [
        {
            "response": {
                "id": f"hcl-{index}",
                "unifiedStandardTitle": "Engineer",
            }
        }
        for index in range(10)
    ]
    session = Mock()
    session.post.side_effect = [
        _hcl_response(records, 20),
        _hcl_response(list(reversed(records)), 20),
    ]
    mock_session.return_value.__enter__.return_value = session

    test_company = company("hcltech")
    test_company.provider.config.search_terms = ["Mumbai"]
    test_company.provider.config.max_pages = 2

    with pytest.raises(
        RuntimeError,
        match="HCLTech pagination stalled",
    ):
        HCLTechAdapter().fetch_jobs(test_company)

    assert session.post.call_count == 2
    output = capsys.readouterr().out
    assert "status=failed pages=2 raw_records=20 processed_records=10" in output
    assert "total=20 unique=10 duplicates=0" in output


@patch("src.providers.hcltech.requests.Session")
def test_hcltech_pagination_allows_partial_id_overlap(
    mock_session,
):
    first_page = [
        {
            "response": {
                "id": f"hcl-{index}",
                "unifiedStandardTitle": "Engineer",
            }
        }
        for index in range(10)
    ]
    second_page = [
        {
            "response": {
                "id": f"hcl-{index}",
                "unifiedStandardTitle": "Engineer",
            }
        }
        for index in range(8, 18)
    ]
    session = Mock()
    session.post.side_effect = [
        _hcl_response(first_page, 20),
        _hcl_response(second_page, 20),
    ]
    mock_session.return_value.__enter__.return_value = session

    test_company = company("hcltech")
    test_company.provider.config.search_terms = ["Mumbai"]
    test_company.provider.config.max_pages = 2

    jobs = HCLTechAdapter().fetch_jobs(test_company)

    assert len(jobs) == 18
    assert session.post.call_count == 2


def test_ibm_payload():
    payload = IBMAdapter._payload(
        "Java", 2, 30
    )

    assert payload["from"] == 30
    assert payload["p"] == 2
    assert payload["size"] == 30
    assert payload["appId"] == "careers"


@patch("src.providers.ibm.requests.Session")
def test_ibm_pagination_advances_by_returned_count(mock_session):
    first_record = {
        "_source": {
            "url": (
                "https://careers.ibm.com/careers/"
                "JobDetail?jobId=1001"
            ),
            "title": "Java Engineer One",
        }
    }
    second_record = {
        "_source": {
            "url": (
                "https://careers.ibm.com/careers/"
                "JobDetail?jobId=1002"
            ),
            "title": "Java Engineer Two",
        }
    }
    responses = []

    for records in ([first_record], [second_record]):
        response = Mock()
        response.status_code = 200
        response.url = "https://www-api.ibm.com/search/api/v2"
        response.headers = {"Content-Type": "application/json"}
        response.json.return_value = {
            "hits": {
                "total": {"value": 2, "relation": "eq"},
                "hits": records,
            }
        }
        response.raise_for_status = Mock()
        responses.append(response)

    session = Mock()
    session.post.side_effect = responses
    mock_session.return_value.__enter__.return_value = session

    test_company = company("ibm")
    test_company.provider.config.search_terms = ["Java"]
    test_company.provider.config.page_size = 2
    test_company.provider.config.max_pages = 2

    jobs = IBMAdapter().fetch_jobs(test_company)

    assert [job.id for job in jobs] == ["1001", "1002"]
    assert [
        call.kwargs["json"]["from"]
        for call in session.post.call_args_list
    ] == [0, 1]


def test_ibm_parse():
    raw = [{
        "url": (
            "https://careers.ibm.com/careers/"
            "JobDetail?jobId=137025"
        ),
        "title": "Application Architect-Microservices",
        "field_keyword_19": "Mumbai, IN",
        "field_keyword_17": "Hybrid",
        "field_keyword_18": "Professional",
        "field_keyword_08": "Software Engineering",
    }]

    jobs = IBMAdapter().parse(
        raw, company("ibm")
    )

    assert len(jobs) == 1
    assert jobs[0].id == "137025"
    assert jobs[0].location == "Mumbai, IN"
    assert jobs[0].remote is False
    assert jobs[0].department == "Software Engineering"


def test_ibm_invalid_url():
    with pytest.raises(ValueError):
        IBMAdapter._job_id(
            "https://example.com/job?id=123"
        )


def test_ibm_deduplication():
    item = {
        "url": (
            "https://careers.ibm.com/careers/"
            "JobDetail?jobId=135137"
        ),
        "title": "Java Developer",
        "field_keyword_19": "Bangalore, IN",
    }

    jobs = IBMAdapter().parse(
        [item, item], company("ibm")
    )

    assert len(jobs) == 1


def _registry_ibm():
    registry_path = Path(__file__).resolve().parent.parent / "config" / "companies.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    return Company.model_validate(
        next(item for item in registry["companies"] if item["id"] == "ibm")
    )


def _ibm_hit(number, title="Java Developer", location="Bangalore, India"):
    return {"_source": {
        "url": f"https://careers.ibm.com/careers/JobDetail?jobId={number}",
        "title": title,
        "field_keyword_19": location,
    }}


def _ibm_run(test_company, responses):
    session = Mock()
    session.post.side_effect = responses
    with patch("src.providers.ibm.requests.Session") as factory:
        factory.return_value.__enter__.return_value = session
        try:
            jobs = IBMAdapter().fetch_jobs(test_company)
        except RuntimeError as exc:
            return session, None, str(exc)
    return session, jobs, None


def _requests(session):
    return [
        (call.kwargs["json"]["sm"]["query"], call.kwargs["json"]["p"],
         call.kwargs["json"]["from"], call.kwargs["json"]["size"])
        for call in session.post.call_args_list
    ]


@pytest.mark.parametrize("unique", [796, 696])
def test_ibm_registry_capacity_completes_stable_796_hits(capsys, unique):
    test_company = _registry_ibm()
    terms = test_company.provider.config.search_terms
    records = [_ibm_hit(number % unique + 1) for number in range(796)]
    responses = [_ibm_response(records[i:i + 30], 796) for i in range(0, 796, 30)]
    responses.extend(_ibm_response([], 0) for _ in terms[1:])

    old_company = test_company.model_copy(deep=True)
    old_company.provider.config.max_pages = 25
    old_session, old_jobs, old_error = _ibm_run(old_company, responses)
    assert old_jobs is None
    assert old_error == "IBM query 'Java' incomplete: 750/796 hits"
    assert len(_requests(old_session)) == 25

    session, jobs, error = _ibm_run(test_company, responses)
    assert error is None
    assert [job.id for job in jobs] == [str(number) for number in range(1, unique + 1)]
    assert [str(job.url) for job in jobs] == [
        f"https://careers.ibm.com/careers/JobDetail?jobId={number}"
        for number in range(1, unique + 1)
    ]
    assert _requests(session) == [
        ("Java", page, (page - 1) * 30, 30) for page in range(1, 28)
    ] + [(term, 1, 0, 30) for term in terms[1:]]
    assert (
        f"raw_records=796 processed_records=796 total=796 "
        f"unique={unique} duplicates={796 - unique}"
    ) in capsys.readouterr().out


@pytest.mark.parametrize(
    ("pages", "expected_ids", "error", "offsets"),
    [
        ([([1, 2], 5), ([3, 4], 6)], None, "IBM inventory changed during pagination", [0, 2]),
        ([([1, 2], 5), ([3, 4], 4)], None, "IBM inventory changed during pagination", [0, 2]),
        ([([1, 2], 4), ([], 4)], None, "IBM query 'Java' incomplete: 2/4 hits", [0, 2]),
        ([([1, 1], 2)], ["1"], None, [0]),
        ([([1, 2], 4), ([2, 3], 4)], ["1", "2", "3"], None, [0, 2]),
        ([([1, 2], 4), ([1, 2], 4)], ["1", "2"], None, [0, 2]),
        ([([1, 2], 3), ([3], 3)], ["1", "2", "3"], None, [0, 2]),
        ([([], 0)], [], None, [0]),
    ],
    ids=["increasing-total", "decreasing-total", "empty-intermediate",
         "within-page-duplicate", "cross-page-duplicate", "repeated-page",
         "short-final-page", "empty-inventory"],
)
def test_ibm_small_inventory_matches_old_cap(pages, expected_ids, error, offsets):
    outcomes = []
    for cap in (25, _registry_ibm().provider.config.max_pages):
        test_company = _registry_ibm()
        test_company.provider.config.search_terms = ["Java"]
        test_company.provider.config.page_size = 2
        test_company.provider.config.max_pages = cap
        responses = [
            _ibm_response([_ibm_hit(number) for number in numbers], total)
            for numbers, total in pages
        ]
        session, jobs, actual_error = _ibm_run(test_company, responses)
        outcomes.append((
            _requests(session),
            None if jobs is None else [job.model_dump(mode="json") for job in jobs],
            actual_error,
        ))
        assert actual_error == error
        assert (None if jobs is None else [job.id for job in jobs]) == expected_ids
        assert _requests(session) == [
            ("Java", page, offset, 2)
            for page, offset in enumerate(offsets, 1)
        ]
    assert outcomes[0] == outcomes[1]


def test_ibm_cap_exhaustion_fails_before_later_terms():
    test_company = _registry_ibm()
    test_company.provider.config.search_terms = ["Java", "Backend"]
    cap = test_company.provider.config.max_pages
    responses = [
        _ibm_response([_ibm_hit(number) for number in range(i * 30, (i + 1) * 30)], cap * 30 + 1)
        for i in range(cap)
    ]
    session, jobs, error = _ibm_run(test_company, responses)
    assert jobs is None
    assert error == f"IBM query 'Java' incomplete: {cap * 30}/{cap * 30 + 1} hits"
    assert _requests(session) == [
        ("Java", page, (page - 1) * 30, 30) for page in range(1, cap + 1)
    ]


@pytest.mark.parametrize(
    ("fail_first", "delivery_fails"), [(False, False), (False, True), (True, False)]
)
def test_ibm_head_equivalent_company_and_notifications(tmp_path, fail_first, delivery_fails):
    outcomes = []
    for label, cap in (("head", 25), ("current", _registry_ibm().provider.config.max_pages)):
        test_company = _registry_ibm()
        test_company.provider.config.search_terms = ["Java", "Backend"]
        test_company.provider.config.max_pages = cap
        responses = (
            [_ibm_response([_ibm_hit(1)], 2), _ibm_response([], 2)]
            if fail_first else [
                _ibm_response([
                    _ibm_hit(1),
                    _ibm_hit(2, "Product Designer"),
                    _ibm_hit(3, location="New York, USA"),
                ], 3),
                _ibm_response([_ibm_hit(1, "Backend Engineer"), _ibm_hit(4)], 2),
            ]
        )
        session = Mock()
        session.post.side_effect = responses
        recovery_path = tmp_path / f"{label}-recovery.json"
        recovery_path.write_text(json.dumps({"ibm": {"failures": 1}}), encoding="utf-8")
        recovery = RecoveryStore(recovery_path)
        store = SeenStore(tmp_path / f"{label}-seen.json")
        store.mark_seen(IBMAdapter().parse([_ibm_hit(1)["_source"]], test_company))
        with patch("src.providers.ibm.requests.Session") as factory:
            factory.return_value.__enter__.return_value = session
            result = _run_company(test_company, IBMAdapter(), JobFilter(), recovery, {})

        pending = store.filter_new(result.matching)
        notifier = Mock()
        if delivery_fails:
            notifier.send_message.side_effect = RuntimeError("offline")
            with pytest.raises(SystemExit):
                _send_notifications(store, notifier, pending, 25, _settings())
        else:
            _send_notifications(store, notifier, pending, 25, _settings())
        outcomes.append((
            _requests(session), result.success, result.coverage_status, result.listing_status,
            result.error, result.jobs_fetched,
            [job.model_dump(mode="json") for job in result.matching],
            [call.args[0] for call in notifier.send_message.call_args_list],
            json.loads((tmp_path / f"{label}-seen.json").read_text(encoding="utf-8")),
            json.loads(recovery_path.read_text(encoding="utf-8")),
        ))
        if fail_first:
            assert _requests(session) == [("Java", 1, 0, 30), ("Java", 2, 1, 30)]
            assert not result.success and result.coverage_status == "failed"
            assert result.listing_status == "failed"
            assert "incomplete" in result.error
            assert notifier.send_message.call_count == 0
            assert json.loads(recovery_path.read_text(encoding="utf-8")) == {"ibm": {"failures": 1}}
        else:
            assert _requests(session) == [("Java", 1, 0, 30), ("Backend", 1, 0, 30)]
            assert result.success and result.coverage_status == "complete"
            assert result.jobs_fetched == 4
            assert [job.id for job in result.matching] == ["1", "4"]
            assert result.matching[0].title == "Backend Engineer"
            assert [job.id for job in pending] == ["4"]
            assert notifier.send_message.call_count == 1
            assert [job.id for job in SeenStore(tmp_path / f"{label}-seen.json").filter_new(pending)] == (
                ["4"] if delivery_fails else []
            )
            assert json.loads(recovery_path.read_text(encoding="utf-8")) == {}
    assert outcomes[0] == outcomes[1]