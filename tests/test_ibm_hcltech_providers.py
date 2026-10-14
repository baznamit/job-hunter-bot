import pytest
from unittest.mock import Mock, patch

from models.company import Company
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
def test_hcltech_zero_results_without_job_list(mock_session):
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


@patch("src.providers.hcltech.requests.Session")
def test_hcltech_rejects_missing_positive_job_list(mock_session):
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
        "totalJobs": 13
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
    ):
        HCLTechAdapter().fetch_jobs(test_company)


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