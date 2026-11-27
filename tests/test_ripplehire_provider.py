import json
from unittest.mock import Mock

import pytest

from models.company import (
    Company,
    CompanyCategory,
    Provider,
    ProviderConfig,
    ProviderStatus,
    ProviderType,
)
from src.providers.ripplehire import RippleHireAdapter


def _company(**config) -> Company:
    return Company(
        id="citiustech",
        name="CitiusTech",
        category=CompanyCategory.PRODUCT,
        priority=2,
        career_page="https://www.citiustech.com/careers",
        provider=Provider(
            type=ProviderType.RIPPLEHIRE,
            status=ProviderStatus.VERIFIED,
            config=ProviderConfig(
                base_url="https://citiustech.ripplehire.com/candidate",
                token="public-token",
                source="CAREERSITE",
                **config,
            ),
        ),
    )


def _response(payload: dict) -> Mock:
    response = Mock()
    response.status_code = 200
    response.url = "https://citiustech.ripplehire.com/candidate/candidatejobsearch"
    response.headers = {}
    response.json.return_value = payload
    response.raise_for_status = Mock()
    return response


def test_parses_ripplehire_job_and_canonical_detail_url():
    jobs = RippleHireAdapter().parse(
        {
            "totalJobCount": 1,
            "jobVoList": [
                {
                    "jobSeq": "924940",
                    "jobTitle": "Lead Engineer - II_UiPath",
                    "locations": "CT Pune (E) - EON",
                }
            ],
        },
        _company(),
    )

    assert len(jobs) == 1
    assert jobs[0].id == "924940"
    assert jobs[0].title == "Lead Engineer - II_UiPath"
    assert jobs[0].location == "CT Pune (E) - EON"
    assert str(jobs[0].url) == (
        "https://citiustech.ripplehire.com/candidate/"
        "?token=public-token&source=CAREERSITE#detail/job/924940"
    )


def test_fetches_all_ripplehire_pages_and_checks_inventory(monkeypatch):
    jobs = [
        {"jobSeq": "job-1", "jobTitle": "Engineer"},
        {"jobSeq": "job-2", "jobTitle": "Engineer"},
        {"jobSeq": "job-3", "jobTitle": "Engineer"},
    ]
    responses = [
        _response({"totalJobCount": 3, "jobVoList": jobs[:2]}),
        _response({"totalJobCount": 3, "jobVoList": jobs[2:]}),
    ]
    session = Mock()
    session.get.return_value = _response({})
    session.post.side_effect = responses
    monkeypatch.setattr(
        "src.providers.ripplehire.requests.Session",
        lambda: session,
    )

    company = _company(page_size=2)
    raw = RippleHireAdapter()._fetch_raw(company)

    assert raw["totalJobCount"] == 3
    assert raw["jobVoList"] == jobs
    assert session.post.call_count == 2
    first_request = session.post.call_args_list[0].kwargs["data"]
    assert json.loads(first_request["careerSiteUrlParams"])["page"] == 0


def test_rejects_incomplete_ripplehire_inventory(monkeypatch):
    session = Mock()
    session.get.return_value = _response({})
    session.post.return_value = _response(
        {
            "totalJobCount": 2,
            "jobVoList": [{"jobSeq": "job-1", "jobTitle": "Engineer"}],
        }
    )
    monkeypatch.setattr(
        "src.providers.ripplehire.requests.Session",
        lambda: session,
    )

    with pytest.raises(ValueError, match="incomplete page"):
        RippleHireAdapter()._fetch_raw(_company(page_size=2))


def test_rejects_ripplehire_page_size_over_limit():
    with pytest.raises(ValueError, match="page_size"):
        RippleHireAdapter()._configuration(_company(page_size=101))
