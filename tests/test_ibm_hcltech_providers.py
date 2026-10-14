import pytest

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


def test_ibm_payload():
    payload = IBMAdapter._payload(
        "Java", 2, 30
    )

    assert payload["from"] == 30
    assert payload["p"] == 2
    assert payload["size"] == 30
    assert payload["appId"] == "careers"


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