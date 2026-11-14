import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import requests

from src.providers.exceptions import ProviderTemporaryError
from src.providers.workday import WorkdayAdapter


def _company():
    return SimpleNamespace(
        id="test-company",
        name="Test Company",
        provider=SimpleNamespace(
            config=SimpleNamespace(
                tenant="test",
                cluster="wd1",
                board="Careers",
                boards=[],
            )
        ),
    )


def _response(status=200, payload=None, *, content_type=None, url=None, history=None, body=None):
    response = requests.Response()
    response.status_code = status
    response.url = url or "https://test.wd1.myworkdayjobs.com/wday/cxs/test/Careers/jobs"
    response.headers = {}
    if content_type is not None:
        response.headers["Content-Type"] = content_type
    response.history = history or []
    if body is None:
        body = json.dumps(payload).encode() if payload is not None else b""
    response._content = body
    response.encoding = "utf-8"
    return response


def _maintenance_response(original_url):
    redirect = _response(
        status=303,
        url=original_url,
        history=[],
    )
    redirect.headers["Location"] = "https://community.workday.com/maintenance-page"
    return _response(
        payload={"html": "maintenance"},
        content_type="text/html",
        url="https://community.workday.com/maintenance-page",
        history=[redirect],
        body=b"<html>maintenance</html>",
    )


def test_maintenance_redirect_is_temporary_and_structural():
    adapter = WorkdayAdapter()
    url = "https://test.wd1.myworkdayjobs.com/wday/cxs/test/Careers/jobs"

    with pytest.raises(ProviderTemporaryError, match="TEMPORARY_MAINTENANCE") as raised:
        adapter._validate_json_response(
            _maintenance_response(url),
            _company(),
            operation="listing",
            board="Careers",
            endpoint=url,
            offset=20,
        )

    message = str(raised.value)
    assert "original_endpoint=" in message
    assert "final_url=https://community.workday.com/maintenance-page" in message
    assert "content_type='text/html'" in message
    assert raised.value.maintenance is True


def test_direct_maintenance_response_is_identified_without_substring_matching():
    adapter = WorkdayAdapter()
    response = _response(
        payload={"maintenance": True},
        url="https://community.workday.com/maintenance-page",
    )

    with pytest.raises(ProviderTemporaryError, match="TEMPORARY_MAINTENANCE"):
        adapter._validate_json_response(
            response,
            _company(),
            operation="detail_location",
            board="Careers",
            endpoint="https://test.example/detail",
            detail_path="/job/example",
        )

    assert not WorkdayAdapter._is_maintenance_url(
        "https://not-community.workday.com/maintenance-page"
    )


@pytest.mark.parametrize(
    "body, expected",
    [
        (b"", "invalid JSON"),
        (b"{bad", "invalid JSON"),
        (b"[]", "unexpected JSON shape"),
    ],
)
def test_json_validation_reports_empty_malformed_and_shape(body, expected):
    adapter = WorkdayAdapter()
    response = _response(body=body, content_type="text/html")

    with pytest.raises(ValueError, match=expected) as raised:
        adapter._validate_json_response(
            response,
            _company(),
            operation="listing",
            board="Careers",
            endpoint=response.url,
            offset=0,
        )

    if body != b"[]":
        assert "preview=" in str(raised.value)


def test_valid_json_does_not_require_json_content_type():
    adapter = WorkdayAdapter()
    data = adapter._validate_json_response(
        _response(
            payload={"total": 1, "jobPostings": []},
            content_type="text/plain",
        ),
        _company(),
        operation="listing",
        board="Careers",
        endpoint="https://test.example/jobs",
        offset=0,
    )
    assert data["total"] == 1


def test_maintenance_on_later_page_never_returns_partial_inventory():
    company = _company()
    adapter = WorkdayAdapter()
    first_url = "https://test.wd1.myworkdayjobs.com/wday/cxs/test/Careers/jobs"
    first = _response(
        payload={"total": 41, "jobPostings": [{"externalPath": "/job/one"}] * 20},
        url=first_url,
    )
    calls = []

    def fake_post(url, *, json, headers, timeout):
        calls.append(json["offset"])
        if json["offset"] == 0:
            return first
        return _maintenance_response(url)

    with patch("src.providers.workday.requests.post", side_effect=fake_post):
        with pytest.raises(ProviderTemporaryError, match="TEMPORARY_MAINTENANCE"):
            adapter._fetch_raw(company)

    assert 0 in calls
    assert len(calls) <= 3


def test_detail_maintenance_stops_new_work_and_preserves_locations():
    adapter = WorkdayAdapter()
    company = _company()
    postings = [
        {
            "externalPath": f"/job/IN-MH-MUMBAI/{index}",
            "locationsText": "IN-MH-MUMBAI-SITE",
            "_workday_board": "Careers",
        }
        for index in range(3)
    ]
    calls = []

    def fake_detail(_company, _board, posting):
        calls.append(posting["externalPath"])
        if len(calls) == 1:
            return "Mumbai, India"
        error = ProviderTemporaryError(
            company="Test Company",
            provider="Workday",
            message="TEMPORARY_MAINTENANCE status=503",
        )
        error.maintenance = True
        raise error

    with patch("src.providers.workday._DETAIL_WORKERS", 1):
        with patch.object(adapter, "_fetch_detail_location", side_effect=fake_detail):
            adapter._enrich_ambiguous_locations(company, postings)

    assert calls == ["/job/IN-MH-MUMBAI/0", "/job/IN-MH-MUMBAI/1"]
    assert postings[0]["_resolved_location"] == "Mumbai, India"
    assert postings[1]["locationsText"] == "IN-MH-MUMBAI-SITE"
    assert postings[2]["locationsText"] == "IN-MH-MUMBAI-SITE"
    assert "_resolved_location" not in postings[1]
    assert "_resolved_location" not in postings[2]
