import pytest
import requests
from unittest.mock import Mock, patch

from models.company import Company
from src.providers.exceptions import ProviderTemporaryError
from src.providers.hcltech import HCLTechAdapter
from src.providers.ibm import IBMAdapter


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