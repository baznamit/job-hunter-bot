from datetime import datetime, timedelta, timezone
from threading import Event
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import requests

from models import Job
from models.company import ProviderType
from src.main import _run_company
from src.providers.base import ProviderAdapter
from src.providers.exceptions import ProviderTemporaryError, parse_retry_after
from src.providers.workday import (
    WorkdayAdapter,
    WorkdayCoverageReport,
    WorkdayRequestPolicy,
)
from src.run_result import CompanyRunResult


def _company():
    return SimpleNamespace(
        id="workday-company",
        name="Workday Company",
        provider=SimpleNamespace(
            type=ProviderType.WORKDAY,
            config=SimpleNamespace(
                tenant="test",
                cluster="wd1",
                board="Careers",
                boards=[],
            ),
        ),
    )


def _posting(number):
    return {
        "externalPath": f"/job/IN-MH-MUMBAI/{number}",
        "locationsText": "IN-MH-MUMBAI-SITE",
        "_workday_board": "Careers",
    }


def _job(number):
    return Job(
        id=str(number),
        title="Engineer",
        company="Workday Company",
        location="Mumbai, India",
        url=f"https://example.com/jobs/{number}",
    )


def test_temporary_error_fields_remain_constructor_compatible():
    old = ProviderTemporaryError("Company", "Workday", "HTTP 429")
    assert old.status is None
    assert old.category is None

    error = ProviderTemporaryError(
        "Company",
        "Workday",
        "rate limited",
        status=429,
        category="rate_limit",
        retry_after="3",
        endpoint="https://example.test/jobs",
        operation="listing",
    )
    assert error.status_code == 429
    assert error.category == "rate_limit"
    assert error.retry_after_seconds == 3
    assert error.endpoint.endswith("/jobs")


def test_retry_after_supports_seconds_http_date_and_rejects_invalid():
    assert parse_retry_after("4") == 4
    now = datetime.now(timezone.utc)
    header = (now + timedelta(seconds=20)).strftime(
        "%a, %d %b %Y %H:%M:%S GMT"
    )
    parsed = parse_retry_after(header, now=now.timestamp())
    assert 19 <= parsed <= 21
    assert parse_retry_after("not-a-date") is None
    assert parse_retry_after(None) is None


def test_policy_defers_when_retry_after_exceeds_budget():
    now = [100.0]
    sleeps = []
    policy = WorkdayRequestPolicy(
        pacing_seconds=0,
        clock=lambda: now[0],
        sleeper=sleeps.append,
    )
    error = ProviderTemporaryError(
        "Company",
        "Workday",
        "rate limited",
        category="rate_limit",
        retry_after_seconds=30,
    )
    policy.after_failure("test.wd1.myworkdayjobs.com", error, 1)
    decision = policy.before_request(
        "test.wd1.myworkdayjobs.com",
        deadline=110,
    )
    assert decision.allowed is False
    assert decision.reason == "time_budget"
    assert sleeps == []


def test_429_is_retried_once_without_changing_identity():
    adapter = WorkdayAdapter(
        WorkdayRequestPolicy(pacing_seconds=0, max_attempts=2)
    )
    company = _company()
    first = requests.Response()
    first.status_code = 429
    first.url = "https://test.wd1.myworkdayjobs.com/jobs"
    first.headers = {"Retry-After": "0"}
    second = requests.Response()
    second.status_code = 200
    second.url = first.url
    second.headers = {}
    second._content = b'{"jobPostings": [], "total": 0}'
    second.encoding = "utf-8"

    with patch(
        "src.providers.workday.requests.post",
        side_effect=[first, second],
    ) as request:
        data = adapter._request_page(
            url=first.url,
            headers={"Referer": "https://test.wd1.myworkdayjobs.com/en-US/Careers"},
            offset=0,
            company=company,
        )

    assert data["total"] == 0
    assert request.call_count == 2


def test_running_success_is_retained_after_parallel_failure():
    adapter = WorkdayAdapter(
        WorkdayRequestPolicy(pacing_seconds=0)
    )
    company = _company()
    release_success = Event()
    second_started = Event()
    calls = []

    def detail(_company, _board, posting):
        calls.append(posting["externalPath"])
        if posting["externalPath"].endswith("/0"):
            second_started.wait(1)
            error = ProviderTemporaryError(
                "Workday Company",
                "Workday",
                "maintenance",
                category="maintenance",
            )
            error.maintenance = True
            release_success.set()
            raise error
        second_started.set()
        release_success.wait(1)
        return "Mumbai, India"

    postings = [_posting(0), _posting(1), _posting(2)]
    with patch("src.providers.workday._DETAIL_WORKERS", 2):
        with patch.object(adapter, "_fetch_detail_location", side_effect=detail):
            report = adapter._enrich_ambiguous_locations(company, postings)

    assert report.enrichment_candidates == 3
    assert report.enrichment_attempted == 2
    assert report.enrichment_resolved == 1
    assert report.enrichment_unresolved == 1
    assert report.enrichment_unstarted == 1
    assert postings[1]["_resolved_location"] == "Mumbai, India"
    assert calls == ["/job/IN-MH-MUMBAI/0", "/job/IN-MH-MUMBAI/1"]


def test_isolated_timeout_allows_remaining_candidates_to_continue():
    adapter = WorkdayAdapter(WorkdayRequestPolicy(pacing_seconds=0))
    company = _company()
    calls = []

    def detail(_company, _board, posting):
        calls.append(posting["externalPath"])
        if posting["externalPath"].endswith("/0"):
            raise ProviderTemporaryError(
                "Workday Company",
                "Workday",
                "timeout",
                category="timeout",
            )
        return "Mumbai, India"

    postings = [_posting(0), _posting(1), _posting(2)]
    with patch("src.providers.workday._DETAIL_WORKERS", 1):
        with patch.object(adapter, "_fetch_detail_location", side_effect=detail):
            report = adapter._enrich_ambiguous_locations(company, postings)

    assert len(calls) == 3
    assert report.enrichment_attempted == 3
    assert report.enrichment_resolved == 2
    assert report.failure_reasons == {"timeout": 1}


def test_partial_workday_report_reaches_company_result_without_shared_state():
    company = _company()
    adapter = MagicMock()
    report = WorkdayCoverageReport(
        enrichment_candidates=3,
        enrichment_attempted=2,
        enrichment_resolved=1,
        enrichment_unresolved=1,
        enrichment_unstarted=1,
        http_attempts=4,
        http_retries=1,
        failure_reasons={"timeout": 1},
    )
    adapter.fetch_jobs_with_report.return_value = ([_job(1)], report)
    recovery = MagicMock()
    recovery.should_attempt.return_value = (True, None)
    job_filter = MagicMock()
    job_filter.should_include.return_value = True

    result = _run_company(
        company,
        adapter,
        job_filter,
        recovery,
        {},
    )

    assert isinstance(result, CompanyRunResult)
    assert result.success is True
    assert result.coverage_status == "partial"
    assert result.enrichment_resolved == 1
    assert result.enrichment_unstarted == 1
    assert result.matching == [_job(1)]
