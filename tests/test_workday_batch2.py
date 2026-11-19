import json
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timedelta, timezone
from threading import Event, Lock
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import requests

from models import Job
from models.company import ProviderType
from src.main import (
    _print_performance_summary,
    _process_jobs_for_company,
    _record_selection_diagnostics,
    _run_company,
)
from src.description_diagnostics import classify_workday_candidate_title
from src.filters import JobFilter
from src.providers.base import ProviderAdapter
from src.providers.exceptions import ProviderTemporaryError, parse_retry_after
from src.providers.workday import (
    _RequestStats,
    WorkdayAdapter,
    WorkdayCoverageReport,
    WorkdayRequestPolicy,
)
from src.run_result import CompanyRunResult
from src.store import SeenStore


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


def _record_fake_detail_call(adapter):
    stats = adapter._current_request_stats()
    if stats is not None:
        stats.attempts += 1


def _response(status, url, body, headers=None):
    response = requests.Response()
    response.status_code = status
    response.url = url
    response.headers = headers or {}
    response._content = json.dumps(body).encode("utf-8")
    response.encoding = "utf-8"
    return response


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
        _record_fake_detail_call(adapter)
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


def test_candidate_accounting_reconciles_without_changing_order(capsys):
    job_filter = JobFilter()
    adapter = WorkdayAdapter(
        WorkdayRequestPolicy(pacing_seconds=0),
        candidate_classifier=lambda title: (
            classify_workday_candidate_title(title, job_filter)
        ),
    )
    postings = [
        {
            **_posting(0),
            "title": "Java Software Engineer",
        },
        {
            **_posting(1),
            "title": "Computer Scientist II",
        },
        {
            **_posting(2),
            "title": "Account Executive",
        },
        {
            **_posting(3),
            "title": None,
        },
    ]
    original_order = [posting["externalPath"] for posting in postings]
    stats_by_path = {}

    def run_candidate(
        company,
        board,
        posting,
        deadline,
    ):
        stats = _RequestStats()
        stats.attempts = 2 if posting["title"] == "Java Software Engineer" else 1
        stats.retries = stats.attempts - 1
        stats_by_path[posting["externalPath"]] = stats
        if posting["title"] == "Account Executive":
            error = ProviderTemporaryError(
                company.name,
                "Workday",
                "HTTP 429",
                category="rate_limit",
                status=429,
            )
            error._workday_stats = stats
            raise error
        return "Mumbai, India", stats

    with patch("src.providers.workday._DETAIL_WORKERS", 1):
        with patch.object(
            adapter,
            "_run_detail_candidate",
            side_effect=run_candidate,
        ):
            report = adapter._enrich_ambiguous_locations(
                _company(),
                postings,
            )

    assert [posting["externalPath"] for posting in postings] == original_order
    assert report.enrichment_candidates == 4
    assert report.enrichment_attempted == 3
    assert report.enrichment_resolved == 2
    assert report.enrichment_unresolved == 1
    assert report.enrichment_unstarted == 1
    assert report.http_attempts == 4
    assert report.http_retries == 1
    assert report.potentially_avoidable_detail_attempts == 1

    accounting = report.candidate_accounting
    assert accounting["direct_title_possible"].candidates == 1
    assert accounting["direct_title_possible"].attempted == 1
    assert accounting["direct_title_possible"].resolved == 1
    assert accounting["direct_title_possible"].retries == 1
    assert (
        accounting["description_promotion_possible"].resolved
        == 1
    )
    assert accounting["selection_inert"].failed == 1
    assert accounting["unknown"].unstarted == 1
    assert sum(item.candidates for item in accounting.values()) == 4
    assert all(
        item.candidates == item.attempted + item.unstarted
        for item in accounting.values()
    )
    assert all(
        item.attempted == item.resolved + item.failed
        for item in accounting.values()
    )

    output = capsys.readouterr().out
    assert "[WORKDAY] CANDIDATE_ACCOUNTING" in output
    assert "potentially_avoidable_detail_attempts=1" in output
    for sensitive in (
        "Java Software Engineer",
        "Computer Scientist II",
        "Account Executive",
    ):
        assert sensitive not in output


def test_successful_workday_enrichment_omits_redundant_summary(capsys):
    adapter = WorkdayAdapter(
        WorkdayRequestPolicy(pacing_seconds=0)
    )
    posting = {
        **_posting(0),
        "title": "Java Software Engineer",
    }

    with patch.object(
        adapter,
        "_fetch_detail_location",
        side_effect=lambda *_: _record_fake_detail_call(adapter)
        or "Mumbai, India",
    ):
        report = adapter._enrich_ambiguous_locations(
            _company(),
            [posting],
        )

    assert report.coverage_status == "complete"
    assert report.http_retries == 0
    assert "[WORKDAY] LOCATION_ENRICHMENT" not in capsys.readouterr().out


def test_retried_workday_enrichment_keeps_detailed_summary(capsys):
    adapter = WorkdayAdapter(
        WorkdayRequestPolicy(pacing_seconds=0)
    )
    posting = {
        **_posting(0),
        "title": "Java Software Engineer",
    }

    def detail(*_):
        stats = adapter._current_request_stats()
        assert stats is not None
        stats.attempts = 2
        stats.retries = 1
        return "Mumbai, India"

    with patch.object(
        adapter,
        "_fetch_detail_location",
        side_effect=detail,
    ):
        report = adapter._enrich_ambiguous_locations(
            _company(),
            [posting],
        )

    assert report.http_retries == 1
    assert "[WORKDAY] LOCATION_ENRICHMENT" in capsys.readouterr().out


def test_candidate_accounting_preserves_enrichment_behavior():
    job_filter = JobFilter()
    inputs = [
        {
            **_posting(index),
            "title": title,
        }
        for index, title in enumerate(
            (
                "Java Software Engineer",
                "Computer Scientist II",
                "Account Executive",
            )
        )
    ]

    def run(classify):
        now = [0.0]
        policy = WorkdayRequestPolicy(
            pacing_seconds=0.2,
            clock=lambda: now[0],
            sleeper=lambda delay: now.__setitem__(
                0,
                now[0] + delay,
            ),
        )
        adapter = WorkdayAdapter(
            policy,
            candidate_classifier=classify,
        )
        postings = [dict(posting) for posting in inputs]
        url = (
            "https://test.wd1.myworkdayjobs.com/wday/cxs/"
            "test/Careers/job/IN-MH-MUMBAI/0"
        )
        response = _response(
            200,
            url,
            {
                "jobPostingInfo": {
                    "location": "Mumbai, India",
                    "country": {"descriptor": "India"},
                }
            },
        )
        with patch("src.providers.workday._DETAIL_WORKERS", 1):
            with patch(
                "src.providers.workday.requests.get",
                return_value=response,
            ) as request:
                report = adapter._enrich_ambiguous_locations(
                    _company(),
                    postings,
                    deadline=10,
                )

        jobs = adapter.parse(
            {"jobPostings": postings},
            _company(),
        )
        with patch(
            "src.description_diagnostics.fetch_description_text",
            return_value="Java Spring Boot backend",
        ):
            matching, direct, promoted = _process_jobs_for_company(
                jobs,
                job_filter,
            )

        return {
            "request_count": request.call_count,
            "elapsed": now[0],
            "postings": postings,
            "jobs": [
                job.model_dump(mode="json")
                for job in jobs
            ],
            "matching": [
                job.model_dump(mode="json")
                for job in matching
            ],
            "direct": direct,
            "promoted": promoted,
            "enrichment": (
                report.enrichment_candidates,
                report.enrichment_attempted,
                report.enrichment_resolved,
                report.enrichment_unresolved,
                report.enrichment_unstarted,
                report.http_attempts,
                report.http_retries,
                report.failure_reasons,
                report.deferral_reasons,
                report.stop_reason,
                report.coverage_status,
            ),
        }

    baseline = run(None)
    accounted = run(
        lambda title: classify_workday_candidate_title(
            title,
            job_filter,
        )
    )

    assert accounted == baseline


def test_candidate_accounting_error_does_not_change_enrichment(capsys):
    adapter = WorkdayAdapter(
        WorkdayRequestPolicy(pacing_seconds=0),
        candidate_classifier=MagicMock(
            side_effect=RuntimeError("diagnostic failure")
        ),
    )
    posting = {
        **_posting(0),
        "title": "Java Software Engineer",
    }

    with patch.object(
        adapter,
        "_fetch_detail_location",
        side_effect=lambda *_: _record_fake_detail_call(adapter)
        or "Mumbai, India",
    ) as mock_fetch:
        report = adapter._enrich_ambiguous_locations(
            _company(),
            [posting],
        )

    assert mock_fetch.call_count == 1
    assert report.enrichment_candidates == 1
    assert report.enrichment_attempted == 1
    assert report.enrichment_resolved == 1
    assert report.candidate_accounting["unknown"].candidates == 1
    assert posting["_resolved_location"] == "Mumbai, India"
    assert (
        "CANDIDATE_ACCOUNTING_WARNING company=workday-company "
        "error=RuntimeError; classified_as=unknown"
        in capsys.readouterr().err
    )


def test_isolated_timeout_allows_remaining_candidates_to_continue():
    adapter = WorkdayAdapter(WorkdayRequestPolicy(pacing_seconds=0))
    company = _company()
    calls = []

    def detail(_company, _board, posting):
        _record_fake_detail_call(adapter)
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


def test_exhausted_detail_rate_limit_stops_unstarted_candidates():
    adapter = WorkdayAdapter(
        WorkdayRequestPolicy(pacing_seconds=0, max_attempts=2)
    )
    postings = [_posting(i) for i in range(6)]

    def rate_limited(url, **_kwargs):
        return _response(429, url, {}, {"Retry-After": "0"})

    with patch("src.providers.workday._DETAIL_WORKERS", 1):
        with patch(
            "src.providers.workday.requests.get", side_effect=rate_limited
        ) as request:
            report = adapter._enrich_ambiguous_locations(_company(), postings)

    assert request.call_count == 2
    assert report.enrichment_candidates == 6
    assert report.enrichment_attempted == 1
    assert report.enrichment_unresolved == 1
    assert report.enrichment_unstarted == 5
    assert report.http_attempts == 2
    assert report.http_retries == 1
    assert report.failure_reasons == {"rate_limit/429": 1}
    assert report.stop_reason == "rate_limit"
    assert report.coverage_status == "partial"
    assert all(
        posting["locationsText"] == "IN-MH-MUMBAI-SITE"
        and "_resolved_location" not in posting
        for posting in postings
    )


def test_detail_rate_limit_followed_by_success_continues_candidates():
    adapter = WorkdayAdapter(
        WorkdayRequestPolicy(pacing_seconds=0, max_attempts=2)
    )
    postings = [_posting(i) for i in range(2)]
    calls = []

    def detail_request(url, **_kwargs):
        calls.append(url)
        if len(calls) == 1:
            return _response(429, url, {}, {"Retry-After": "0"})
        return _response(
            200,
            url,
            {"jobPostingInfo": {
                "location": "Mumbai, India",
                "country": {"descriptor": "India"},
            }},
        )

    with patch("src.providers.workday._DETAIL_WORKERS", 1):
        with patch("src.providers.workday.requests.get", side_effect=detail_request):
            report = adapter._enrich_ambiguous_locations(_company(), postings)

    assert len(calls) == 3
    assert report.enrichment_resolved == 2
    assert report.enrichment_unstarted == 0
    assert (report.http_attempts, report.http_retries) == (3, 1)
    assert report.stop_reason is None
    assert report.coverage_status == "complete"


def test_rate_limit_retains_completed_and_inflight_detail_results():
    adapter = WorkdayAdapter(
        WorkdayRequestPolicy(pacing_seconds=0, max_attempts=2)
    )
    postings = [_posting(i) for i in range(4)]
    for posting in postings:
        posting["title"] = "Engineer"

    inflight_started = Event()
    release_inflight = Event()
    failure_observed = Event()

    def detail_request(url, **_kwargs):
        number = int(url.rsplit("/", 1)[-1])
        if number == 1:
            assert inflight_started.wait(5)
            return _response(429, url, {}, {"Retry-After": "0"})
        if number == 2:
            inflight_started.set()
            assert release_inflight.wait(5)
        return _response(
            200,
            url,
            {"jobPostingInfo": {
                "location": "Mumbai, India",
                "country": {"descriptor": "India"},
            }},
        )

    def observe_failure(futures, **kwargs):
        done, pending = wait(futures, **kwargs)
        if any(
            isinstance(future.exception(), ProviderTemporaryError)
            and future.exception().category == "rate_limit"
            for future in done
        ):
            failure_observed.set()
        return done, pending

    with patch("src.providers.workday._DETAIL_WORKERS", 2):
        with patch("src.providers.workday.wait", side_effect=observe_failure):
            with patch(
                "src.providers.workday.requests.get", side_effect=detail_request
            ) as request:
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(
                        adapter._enrich_ambiguous_locations, _company(), postings
                    )
                    try:
                        assert failure_observed.wait(5)
                    finally:
                        release_inflight.set()
                    report = future.result(timeout=5)

    assert request.call_count == 4
    assert report.enrichment_candidates == 4
    assert report.enrichment_attempted == 3
    assert report.enrichment_resolved == 2
    assert report.enrichment_unresolved == 1
    assert report.enrichment_unstarted == 1
    assert (report.http_attempts, report.http_retries) == (4, 1)
    assert report.stop_reason == "rate_limit"
    assert report.coverage_status == "partial"
    assert postings[0]["_resolved_location"] == "Mumbai, India"
    assert postings[2]["_resolved_location"] == "Mumbai, India"
    assert "_resolved_location" not in postings[1]
    assert "_resolved_location" not in postings[3]
    assert postings[3]["locationsText"] == "IN-MH-MUMBAI-SITE"
    jobs = adapter.parse({"jobPostings": postings}, _company())
    assert [job.id for job in jobs] == [posting["externalPath"] for posting in postings]
    assert all(
        str(job.url) == f"https://test.wd1.myworkdayjobs.com/en-US/Careers{posting['externalPath']}"
        for job, posting in zip(jobs, postings)
    )


@pytest.mark.parametrize("failure", ["server_error", "connection_error"])
def test_other_exhausted_detail_errors_continue_candidates(failure):
    adapter = WorkdayAdapter(
        WorkdayRequestPolicy(pacing_seconds=0, max_attempts=2, backoff_seconds=(0,))
    )
    postings = [_posting(i) for i in range(3)]

    def detail_request(url, **_kwargs):
        if url.endswith("/0"):
            if failure == "connection_error":
                raise requests.ConnectionError("offline test")
            return _response(503, url, {}, {"Retry-After": "0"})
        return _response(
            200,
            url,
            {"jobPostingInfo": {
                "location": "Mumbai, India",
                "country": {"descriptor": "India"},
            }},
        )

    with patch("src.providers.workday._DETAIL_WORKERS", 1):
        with patch(
            "src.providers.workday.requests.get", side_effect=detail_request
        ) as request:
            report = adapter._enrich_ambiguous_locations(_company(), postings)

    assert request.call_count == 4
    assert report.enrichment_attempted == 3
    assert report.enrichment_resolved == 2
    assert report.enrichment_unresolved == 1
    assert report.enrichment_unstarted == 0
    assert (report.http_attempts, report.http_retries) == (4, 1)
    assert report.failure_reasons == {
        "server_error/503" if failure == "server_error" else "connection_error": 1
    }
    assert report.stop_reason is None
    assert report.coverage_status == "partial"


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


def test_waiting_request_rechecks_a_cooldown_extension():
    now = [0.0]
    sleeps = []
    host = "tenant.wd1.myworkdayjobs.com"
    policy = None

    def sleep(delay):
        sleeps.append(delay)
        if len(sleeps) == 1:
            now[0] += delay / 2
            policy.after_failure(
                host,
                ProviderTemporaryError(
                    "Company", "Workday", "extended", retry_after_seconds=30
                ),
                1,
            )
            now[0] += delay / 2
        else:
            now[0] += delay

    policy = WorkdayRequestPolicy(
        pacing_seconds=0,
        clock=lambda: now[0],
        sleeper=sleep,
    )
    policy.after_failure(
        host,
        ProviderTemporaryError(
            "Company", "Workday", "initial", retry_after_seconds=10
        ),
        1,
    )

    decision = policy.before_request(host, deadline=100)

    assert decision.allowed is True
    assert sleeps == [10, 25]
    assert now[0] == 35


@pytest.mark.parametrize("category", ["maintenance", "access_challenge"])
def test_waiting_request_rechecks_blocking_and_expired_deadline(category):
    host = "tenant.wd1.myworkdayjobs.com"
    now = [0.0]

    def block_while_waiting(delay):
        policy.after_failure(
            host,
            ProviderTemporaryError(
                "Company", "Workday", "blocked", category=category
            ),
            1,
        )
        now[0] += delay

    policy = WorkdayRequestPolicy(
        pacing_seconds=0,
        clock=lambda: now[0],
        sleeper=block_while_waiting,
    )
    policy.after_failure(
        host,
        ProviderTemporaryError(
            "Company", "Workday", "cooldown", retry_after_seconds=5
        ),
        1,
    )

    decision = policy.before_request(host, deadline=20)
    assert decision.allowed is False
    assert decision.reason == category

    now[0] = 0
    policy = WorkdayRequestPolicy(
        pacing_seconds=0,
        clock=lambda: now[0],
        sleeper=lambda delay: now.__setitem__(0, now[0] + delay + 2),
    )
    policy.after_failure(
        host,
        ProviderTemporaryError(
            "Company", "Workday", "cooldown", retry_after_seconds=2
        ),
        1,
    )
    decision = policy.before_request(host, deadline=3)
    assert decision.allowed is False
    assert decision.reason == "time_budget"


def test_pacing_is_serialized_after_wakeup_and_hosts_are_independent():
    clock_lock = Lock()
    now = [0.0]
    sleep_lock = Lock()
    initial_sleep_count = [0]
    first_waiting = Event()
    both_waiting = Event()
    release_waiters = Event()
    first_dispatched = Event()
    dispatch_times = []

    def clock():
        with clock_lock:
            return now[0]

    def sleep(delay):
        if not release_waiters.is_set():
            with sleep_lock:
                initial_sleep_count[0] += 1
                first_waiting.set()
                if initial_sleep_count[0] == 2:
                    both_waiting.set()
            assert release_waiters.wait(2)
            return
        assert first_dispatched.wait(2)
        with clock_lock:
            now[0] += delay

    policy = WorkdayRequestPolicy(
        pacing_seconds=0.05,
        clock=clock,
        sleeper=sleep,
    )
    assert policy.before_request("shared-host", None).allowed

    def request():
        decision = policy.before_request("shared-host", None)
        with clock_lock:
            dispatch_times.append(now[0])
        first_dispatched.set()
        return decision

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(request)
        assert first_waiting.wait(2)
        second = executor.submit(request)
        assert both_waiting.wait(2)
        with clock_lock:
            now[0] = 0.05
        release_waiters.set()
        decisions = [first.result(timeout=2), second.result(timeout=2)]

    assert all(decision.allowed for decision in decisions)
    assert all(
        right - left >= 0.05 - 1e-9
        for left, right in zip(dispatch_times, dispatch_times[1:])
    )

    policy.after_failure(
        "blocked-host",
        ProviderTemporaryError(
            "Company", "Workday", "cooldown", retry_after_seconds=100
        ),
        1,
    )
    assert policy.before_request("other-host", deadline=clock() + 1).allowed


def test_deadline_expires_after_admission_while_other_host_proceeds():
    now = [0.0]
    admitted = Event()
    release = Event()
    policy = WorkdayRequestPolicy(pacing_seconds=0.2, clock=lambda: now[0])
    adapter = WorkdayAdapter(policy)
    original_before_request = policy.before_request
    delayed_url = "https://test.wd1.myworkdayjobs.com/jobs"
    other_url = "https://other.wd1.myworkdayjobs.com/jobs"

    def pause_after_admission(host, deadline):
        decision = original_before_request(host, deadline)
        if host == "test.wd1.myworkdayjobs.com":
            admitted.set()
            assert release.wait(5)
        return decision

    def post(url, **_kwargs):
        return _response(200, url, {"jobPostings": [], "total": 0})

    def page(url):
        return adapter._run_page_request(
            url=url,
            headers={"Referer": "https://test/en-US/Careers"},
            offset=0,
            company=_company(),
            deadline=10,
        )

    with patch.object(policy, "before_request", side_effect=pause_after_admission):
        with patch("src.providers.workday.requests.post", side_effect=post) as request:
            with ThreadPoolExecutor(max_workers=1) as executor:
                delayed = executor.submit(page, delayed_url)
                try:
                    assert admitted.wait(5)
                    _, other_stats = page(other_url)
                    now[0] = 10
                finally:
                    release.set()
                with pytest.raises(ProviderTemporaryError) as raised:
                    delayed.result(timeout=5)

    assert request.call_count == 1
    assert request.call_args.args[0] == other_url
    assert (other_stats.attempts, other_stats.retries) == (1, 0)
    assert raised.value.category == "deferred"
    assert raised.value.deferral_reason == "time_budget"
    assert raised.value.deferred_after_attempt is False
    assert (
        raised.value._workday_stats.attempts,
        raised.value._workday_stats.retries,
    ) == (0, 0)


def test_deadline_expires_after_retry_admission_without_counting_retry():
    now = [0.0]
    policy = WorkdayRequestPolicy(
        pacing_seconds=0, max_attempts=2, clock=lambda: now[0]
    )
    adapter = WorkdayAdapter(policy)
    original_before_request = policy.before_request
    admissions = []
    url = "https://test.wd1.myworkdayjobs.com/jobs"

    def pause_after_retry_admission(host, deadline):
        decision = original_before_request(host, deadline)
        admissions.append(decision)
        if len(admissions) == 2:
            now[0] = 10
        return decision

    with patch.object(
        policy, "before_request", side_effect=pause_after_retry_admission
    ):
        with patch(
            "src.providers.workday.requests.post",
            return_value=_response(429, url, {}, {"Retry-After": "0"}),
        ) as request:
            with pytest.raises(ProviderTemporaryError) as raised:
                adapter._run_page_request(
                    url=url,
                    headers={"Referer": "https://test/en-US/Careers"},
                    offset=0,
                    company=_company(),
                    deadline=10,
                )

    assert len(admissions) == 2
    assert request.call_count == 1
    assert raised.value.category == "deferred"
    assert raised.value.deferral_reason == "time_budget"
    assert raised.value.deferred_after_attempt is True
    assert (
        raised.value._workday_stats.attempts,
        raised.value._workday_stats.retries,
    ) == (1, 0)


def test_inflight_request_can_complete_after_deadline():
    now = [0.0]
    started = Event()
    release = Event()
    policy = WorkdayRequestPolicy(pacing_seconds=0, clock=lambda: now[0])
    adapter = WorkdayAdapter(policy)
    url = "https://test.wd1.myworkdayjobs.com/jobs"

    def post(_url, **_kwargs):
        started.set()
        assert release.wait(5)
        return _response(200, url, {"jobPostings": [], "total": 0})

    with patch("src.providers.workday.requests.post", side_effect=post):
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                adapter._run_page_request,
                url=url,
                headers={"Referer": "https://test/en-US/Careers"},
                offset=0,
                company=_company(),
                deadline=10,
            )
            try:
                assert started.wait(5)
                now[0] = 10
            finally:
                release.set()
            data, stats = future.result(timeout=5)

    assert data["total"] == 0
    assert (stats.attempts, stats.retries) == (1, 0)


def test_detail_expiry_after_admission_reports_partial_coverage():
    now = [0.0]
    policy = WorkdayRequestPolicy(pacing_seconds=0, clock=lambda: now[0])
    adapter = WorkdayAdapter(policy)
    original_before_request = policy.before_request

    def pause_after_admission(host, deadline):
        decision = original_before_request(host, deadline)
        now[0] = 10
        return decision

    with patch.object(policy, "before_request", side_effect=pause_after_admission):
        with patch("src.providers.workday.requests.get") as request:
            report = adapter._enrich_ambiguous_locations(
                _company(), [_posting(1)], deadline=10
            )

    assert request.call_count == 0
    assert report.coverage_status == "partial"
    assert report.enrichment_attempted == 0
    assert report.enrichment_unstarted == 1
    assert report.deferred_before_attempt == 1
    assert report.deferral_reasons == {"before_attempt:time_budget": 1}
    assert (report.http_attempts, report.http_retries) == (0, 0)


def test_request_stats_count_dispatches_only():
    company = _company()
    url = "https://test.wd1.myworkdayjobs.com/jobs"
    headers = {"Referer": "https://test.wd1.myworkdayjobs.com/en-US/Careers"}
    success = _response(200, url, {"jobPostings": [], "total": 0})

    adapter = WorkdayAdapter(WorkdayRequestPolicy(pacing_seconds=0))
    with patch("src.providers.workday.requests.post", return_value=success):
        _, stats = adapter._run_page_request(
            url=url,
            headers=headers,
            offset=0,
            company=company,
            deadline=10**10,
        )
    assert (stats.attempts, stats.retries) == (1, 0)

    rate_limited = _response(
        429,
        url,
        {},
        {"Retry-After": "0"},
    )
    adapter = WorkdayAdapter(
        WorkdayRequestPolicy(pacing_seconds=0, max_attempts=2)
    )
    with patch(
        "src.providers.workday.requests.post",
        side_effect=[rate_limited, success],
    ) as request:
        _, stats = adapter._run_page_request(
            url=url,
            headers=headers,
            offset=0,
            company=company,
            deadline=10**10,
        )
    assert request.call_count == 2
    assert (stats.attempts, stats.retries) == (2, 1)


def test_retry_deferred_after_failure_keeps_actual_call_counters():
    now = [0.0]
    adapter = WorkdayAdapter(
        WorkdayRequestPolicy(
            pacing_seconds=0,
            max_attempts=2,
            clock=lambda: now[0],
            sleeper=lambda delay: now.__setitem__(0, now[0] + delay),
        )
    )
    url = "https://test.wd1.myworkdayjobs.com/jobs"
    response = _response(
        429,
        url,
        {},
        {"Retry-After": "30"},
    )
    with patch(
        "src.providers.workday.requests.post",
        return_value=response,
    ) as request:
        with pytest.raises(ProviderTemporaryError) as raised:
            adapter._run_page_request(
                url=url,
                headers={"Referer": "https://test/en-US/Careers"},
                offset=0,
                company=_company(),
                deadline=10,
            )

    stats = raised.value._workday_stats
    assert request.call_count == 1
    assert (stats.attempts, stats.retries) == (1, 0)
    assert raised.value.deferral_reason == "time_budget"
    assert raised.value.deferred_after_attempt is True


def test_retry_exhaustion_counts_each_invocation_once():
    adapter = WorkdayAdapter(
        WorkdayRequestPolicy(pacing_seconds=0, max_attempts=2)
    )
    url = "https://test.wd1.myworkdayjobs.com/jobs"
    responses = [
        _response(429, url, {}, {"Retry-After": "0"}),
        _response(429, url, {}, {"Retry-After": "0"}),
    ]
    with patch(
        "src.providers.workday.requests.post",
        side_effect=responses,
    ) as request:
        with pytest.raises(ProviderTemporaryError) as raised:
            adapter._run_page_request(
                url=url,
                headers={"Referer": "https://test/en-US/Careers"},
                offset=0,
                company=_company(),
                deadline=10**10,
            )
    assert request.call_count == 2
    assert (
        raised.value._workday_stats.attempts,
        raised.value._workday_stats.retries,
    ) == (2, 1)


def test_deferral_before_first_request_and_timeout_invocation_accounting():
    now = [0.0]
    adapter = WorkdayAdapter(
        WorkdayRequestPolicy(
            pacing_seconds=0,
            clock=lambda: now[0],
            sleeper=lambda delay: now.__setitem__(0, now[0] + delay),
        )
    )
    url = "https://test.wd1.myworkdayjobs.com/jobs"
    with patch("src.providers.workday.requests.post") as request:
        with pytest.raises(ProviderTemporaryError) as raised:
            adapter._run_page_request(
                url=url,
                headers={"Referer": "https://test/en-US/Careers"},
                offset=0,
                company=_company(),
                deadline=0,
            )
    assert request.call_count == 0
    assert (
        raised.value._workday_stats.attempts,
        raised.value._workday_stats.retries,
    ) == (0, 0)
    assert raised.value.deferral_reason == "time_budget"
    assert raised.value.deferred_after_attempt is False

    adapter = WorkdayAdapter(
        WorkdayRequestPolicy(pacing_seconds=0, max_attempts=1)
    )
    with patch(
        "src.providers.workday.requests.post",
        side_effect=requests.Timeout("slow"),
    ) as request:
        with pytest.raises(ProviderTemporaryError) as raised:
            adapter._run_page_request(
                url=url,
                headers={"Referer": "https://test/en-US/Careers"},
                offset=0,
                company=_company(),
                deadline=10**10,
            )
    assert request.call_count == 1
    assert (
        raised.value._workday_stats.attempts,
        raised.value._workday_stats.retries,
    ) == (1, 0)


def test_failed_first_listing_page_retains_started_attempt_count():
    now = [0.0]
    adapter = WorkdayAdapter(
        WorkdayRequestPolicy(
            pacing_seconds=0,
            max_attempts=2,
            backoff_seconds=(30,),
            clock=lambda: now[0],
        )
    )
    url = "https://test.wd1.myworkdayjobs.com/wday/cxs/test/Careers/jobs"
    response = _response(429, url, {}, {"Retry-After": "30"})
    report = WorkdayCoverageReport()
    with patch(
        "src.providers.workday.requests.post",
        return_value=response,
    ) as request:
        with pytest.raises(ProviderTemporaryError):
            adapter._fetch_board(
                _company(),
                "Careers",
                report=report,
                deadline=10,
            )

    assert request.call_count == 1
    assert report.http_attempts == 1
    assert report.http_retries == 0


def test_concurrent_listing_failure_collects_all_started_request_counts():
    now = [0.0]
    adapter = WorkdayAdapter(
        WorkdayRequestPolicy(
            pacing_seconds=0,
            max_attempts=1,
            clock=lambda: now[0],
        )
    )
    company = _company()
    url = "https://test.wd1.myworkdayjobs.com/wday/cxs/test/Careers/jobs"
    page_started = []
    lock = Lock()
    all_pages_started = Event()

    def post(_url, *, json, **_kwargs):
        offset = json["offset"]
        if offset == 0:
            return _response(
                200,
                url,
                {
                    "jobPostings": [{"externalPath": f"/job/{i}"} for i in range(20)],
                    "total": 80,
                },
            )
        with lock:
            page_started.append(offset)
            if len(page_started) == 3:
                all_pages_started.set()
        assert all_pages_started.wait(2)
        if offset == 20:
            return _response(429, url, {}, {})
        return _response(
            200,
            url,
            {
                "jobPostings": [
                    {"externalPath": f"/job/{offset + index}"}
                    for index in range(20)
                ],
                "total": 0,
            },
        )

    report = WorkdayCoverageReport()
    with patch("src.providers.workday.requests.post", side_effect=post):
        with pytest.raises(ProviderTemporaryError):
            adapter._fetch_board(
                company,
                "Careers",
                report=report,
                deadline=100,
            )

    assert sorted(page_started) == [20, 40, 60]
    assert report.http_attempts == 4
    assert report.http_retries == 0


def test_enrichment_counts_candidates_only_after_detail_dispatch():
    now = [5.0]
    adapter = WorkdayAdapter(
        WorkdayRequestPolicy(
            pacing_seconds=0,
            clock=lambda: now[0],
        )
    )
    report = adapter._enrich_ambiguous_locations(
        _company(),
        [_posting(1)],
        deadline=4,
    )
    assert report.enrichment_candidates == 1
    assert report.enrichment_attempted == 0
    assert report.enrichment_unstarted == 1
    assert report.enrichment_resolved == report.enrichment_unresolved == 0
    assert report.deferred_before_attempt == 1
    assert report.deferral_reasons == {"before_attempt:time_budget": 1}


def test_enrichment_retry_deferral_is_attempted_and_structured():
    now = [0.0]
    adapter = WorkdayAdapter(
        WorkdayRequestPolicy(
            pacing_seconds=0,
            max_attempts=2,
            clock=lambda: now[0],
        )
    )
    url = (
        "https://test.wd1.myworkdayjobs.com/wday/cxs/"
        "test/Careers/job/IN-MH-MUMBAI/1"
    )
    response = _response(429, url, {}, {"Retry-After": "30"})
    with patch("src.providers.workday.requests.get", return_value=response) as request:
        report = adapter._enrich_ambiguous_locations(
            _company(),
            [_posting(1)],
            deadline=10,
        )

    assert request.call_count == 1
    assert report.enrichment_candidates == report.enrichment_attempted == 1
    assert report.enrichment_unresolved == 1
    assert report.enrichment_unstarted == 0
    assert report.http_attempts == 1
    assert report.http_retries == 0
    assert report.deferred_after_attempt == 1
    assert report.deferral_reasons == {"after_attempt:time_budget": 1}


def test_valid_detail_without_location_is_not_a_transport_failure():
    adapter = WorkdayAdapter(WorkdayRequestPolicy(pacing_seconds=0))
    url = (
        "https://test.wd1.myworkdayjobs.com/wday/cxs/"
        "test/Careers/job/IN-MH-MUMBAI/1"
    )
    response = _response(200, url, {"jobPostingInfo": {}})
    with patch("src.providers.workday.requests.get", return_value=response):
        report = adapter._enrich_ambiguous_locations(
            _company(),
            [_posting(1)],
            deadline=10**10,
        )

    assert report.enrichment_attempted == 1
    assert report.enrichment_unresolved == 1
    assert report.failure_reasons == {"no_usable_location": 1}
    assert report.http_attempts == 1


def test_workday_settings_defaults_overrides_and_validation():
    defaults = WorkdayRequestPolicy.from_settings(None)
    assert defaults.pacing_seconds == 0.2
    assert defaults.max_attempts == 2
    assert defaults.company_budget_seconds == 120
    assert defaults.backoff_seconds == (1.0, 3.0)

    configured = WorkdayRequestPolicy.from_settings(
        {
            "request_pacing_seconds": 0.1,
            "max_attempts": 3,
            "company_budget_seconds": 17,
            "backoff_seconds": [2, 4.5],
        }
    )
    adapter = WorkdayAdapter(configured)
    deadlines = []

    def raw(_company, *, report, deadline):
        deadlines.append(deadline)
        return {"jobPostings": []}

    before = time.monotonic()
    with patch.object(adapter, "_fetch_raw", side_effect=raw):
        jobs, _ = adapter.fetch_jobs_with_report(_company())
    assert jobs == []
    assert before + 17 <= deadlines[0] <= time.monotonic() + 17
    assert configured.pacing_seconds == 0.1
    assert configured.max_attempts == 3
    assert configured.backoff_seconds == (2, 4.5)

    invalid = [
        {"request_pacing_seconds": True},
        {"request_pacing_seconds": float("inf")},
        {"request_pacing_seconds": 10**1000},
        {"max_attempts": True},
        {"max_attempts": 1.5},
        {"max_attempts": 0},
        {"company_budget_seconds": True},
        {"company_budget_seconds": float("nan")},
        {"company_budget_seconds": 0},
        {"backoff_seconds": [False]},
        {"backoff_seconds": [-1]},
        {"backoff_seconds": [float("inf")]},
        {"backoff_seconds": []},
    ]
    for settings in invalid:
        with pytest.raises(ValueError):
            WorkdayRequestPolicy.from_settings(settings)


def test_invalid_workday_settings_fail_before_registry_or_network(monkeypatch):
    from src import main as main_module

    monkeypatch.setattr(
        main_module,
        "_settings",
        lambda: {
            "telegram": {"max_jobs_per_message": 25},
            "workday": {"max_attempts": True},
        },
    )
    with patch("src.main.load_registry") as load_registry:
        with pytest.raises(ValueError, match="max_attempts"):
            main_module.main()
    load_registry.assert_not_called()


def test_processing_failure_after_fetch_is_failed_but_listing_remains_complete():
    company = _company()
    adapter = MagicMock()
    adapter.fetch_jobs_with_report.return_value = ([_job(1)], WorkdayCoverageReport())
    recovery = MagicMock()
    recovery.should_attempt.return_value = (True, None)

    with patch("src.main._process_jobs_for_company", side_effect=RuntimeError("boom")):
        result = _run_company(
            company,
            adapter,
            MagicMock(),
            recovery,
            {},
        )

    assert result.success is False
    assert result.skipped is False
    assert result.coverage_status == "failed"
    assert result.listing_status == "complete"
    assert result.jobs_fetched == 1
    assert "boom" in result.error


def test_invalid_workday_inventory_flows_to_failed_company_result():
    company = _company()
    adapter = WorkdayAdapter(
        WorkdayRequestPolicy(pacing_seconds=0)
    )
    recovery = MagicMock()
    recovery.should_attempt.return_value = (True, None)
    url = (
        "https://test.wd1.myworkdayjobs.com/"
        "wday/cxs/test/Careers/jobs"
    )

    with patch(
        "src.providers.workday.requests.post",
        return_value=_response(200, url, {"total": 0}),
    ):
        result = _run_company(
            company,
            adapter,
            MagicMock(),
            recovery,
            {},
        )

    assert result.success is False
    assert result.listing_status == "failed"
    assert result.coverage_status == "failed"
    assert result.jobs_fetched == 0
    assert result.matching == []
    assert result.http_attempts == 1
    recovery.clear.assert_not_called()


def test_summary_categories_reconcile_and_keep_expected_skips_separate(capsys):
    results = [
        CompanyRunResult(
            "a",
            "Complete",
            "Workday",
            success=True,
            http_attempts=1,
        ),
        CompanyRunResult(
            "b",
            "Partial",
            "Workday",
            success=True,
            coverage_status="partial",
            http_attempts=3,
            http_retries=1,
        ),
        CompanyRunResult(
            "c", "Failed", "Workday", success=False, coverage_status="failed"
        ),
        CompanyRunResult(
            "d",
            "Skipped",
            "Workday",
            success=False,
            skipped=True,
            coverage_status="skipped",
        ),
    ]
    _print_performance_summary(results, 1.0, 0)
    output = capsys.readouterr().out
    assert "Successful          : 2" in output
    assert (
        "Workday HTTP attempts/retries (instrumented only): 4/1"
        in output
    )
    assert "Complete            : 1" in output
    assert "Partial enrichment  : 1" in output
    assert "Failed              : 1" in output
    assert "Skipped cooldown    : 1" in output


def test_selection_diagnostics_reconcile_global_plan_without_writing_state(tmp_path):
    seen_path = tmp_path / "seen.json"
    store = SeenStore(seen_path)
    seen = _job("seen")
    shared = _job("shared")
    only_second = _job("second")
    store.mark_seen([seen])
    state_before = seen_path.read_bytes()

    first = CompanyRunResult(
        "a",
        "First",
        "Workday",
        matching=[seen, shared, shared],
    )
    second = CompanyRunResult(
        "b",
        "Second",
        "Workday",
        matching=[seen, shared, only_second],
    )
    new_jobs = store.filter_new(first.matching + second.matching)

    _record_selection_diagnostics([first, second], store, new_jobs)

    assert first.unique_matching_urls == 2
    assert first.seen_urls == 1
    assert first.duplicate_matching_records == 1
    assert first.new_unique_urls == 1
    assert second.unique_matching_urls == 3
    assert second.seen_urls == 1
    assert second.new_unique_urls == 1
    assert second.duplicate_suppressed_urls == 1
    assert second.cross_company_duplicate_urls == 2
    assert first.new_unique_urls + second.new_unique_urls == len(new_jobs)
    assert seen_path.read_bytes() == state_before


def test_failed_company_does_not_suppress_another_companies_notification(
    tmp_path,
    monkeypatch,
    capsys,
):
    from src import main as main_module

    companies = [
        SimpleNamespace(
            id="valid",
            name="Valid Company",
            enabled=True,
            provider=SimpleNamespace(type=ProviderType.GREENHOUSE),
        ),
        SimpleNamespace(
            id="failed",
            name="Failed Company",
            enabled=True,
            provider=SimpleNamespace(type=ProviderType.GREENHOUSE),
        ),
    ]
    monkeypatch.setattr(
        main_module,
        "_settings",
        lambda: {
            "telegram": {"max_jobs_per_message": 25},
            "runtime": {"max_workers": 2, "performance_top_n": 5},
        },
    )
    monkeypatch.setattr(
        main_module,
        "load_registry",
        lambda: SimpleNamespace(companies=companies),
    )
    monkeypatch.setattr(
        main_module,
        "_ADAPTERS",
        {ProviderType.GREENHOUSE: object()},
    )
    monkeypatch.setattr(main_module, "_SEEN_FILE", tmp_path / "seen.json")
    monkeypatch.setattr(
        main_module,
        "_RECOVERY_FILE",
        tmp_path / "recovery.json",
    )
    monkeypatch.setattr(main_module, "TelegramNotifier", MagicMock)

    def run_company(company, *_args):
        if company.id == "valid":
            return CompanyRunResult(
                "valid",
                "Valid Company",
                "Greenhouse",
                matching=[_job(99)],
            )
        return CompanyRunResult(
            "failed",
            "Failed Company",
            "Greenhouse",
            success=False,
            coverage_status="failed",
            listing_status="failed",
            matching=[_job(100)],
            error="provider unavailable",
        )

    monkeypatch.setattr(main_module, "_run_company", run_company)
    with patch("src.main._send_notifications") as send:
        main_module.main()

    assert send.call_count == 1
    assert send.call_args.args[2] == [_job(99)]
    output = capsys.readouterr().out
    assert "Complete            : 1" in output
    assert "Failed              : 1" in output
    assert "new_unique_urls=1" in output


def test_zero_new_summary_keeps_coverage_warning_and_does_not_send(
    tmp_path,
    monkeypatch,
    capsys,
):
    from src import main as main_module

    companies = [
        SimpleNamespace(
            id="known",
            name="Known Company",
            enabled=True,
            provider=SimpleNamespace(type=ProviderType.GREENHOUSE),
        ),
        SimpleNamespace(
            id="failed",
            name="Failed Company",
            enabled=True,
            provider=SimpleNamespace(type=ProviderType.GREENHOUSE),
        ),
    ]
    seen_path = tmp_path / "seen.json"
    store = SeenStore(seen_path)
    store.mark_seen([_job(101)])
    state_before = seen_path.read_bytes()

    monkeypatch.setattr(
        main_module,
        "_settings",
        lambda: {
            "telegram": {"max_jobs_per_message": 25},
            "runtime": {"max_workers": 2, "performance_top_n": 5},
        },
    )
    monkeypatch.setattr(
        main_module,
        "load_registry",
        lambda: SimpleNamespace(companies=companies),
    )
    monkeypatch.setattr(
        main_module,
        "_ADAPTERS",
        {ProviderType.GREENHOUSE: object()},
    )
    monkeypatch.setattr(main_module, "_SEEN_FILE", seen_path)
    monkeypatch.setattr(
        main_module,
        "_RECOVERY_FILE",
        tmp_path / "recovery.json",
    )
    monkeypatch.setattr(main_module, "TelegramNotifier", MagicMock)

    def run_company(company, *_args):
        if company.id == "known":
            return CompanyRunResult(
                "known",
                "Known Company",
                "Greenhouse",
                matching=[_job(101)],
            )
        return CompanyRunResult(
            "failed",
            "Failed Company",
            "Greenhouse",
            success=False,
            coverage_status="failed",
            listing_status="failed",
            error="provider unavailable",
        )

    monkeypatch.setattr(main_module, "_run_company", run_company)
    with patch("src.main._send_notifications") as send:
        main_module.main()

    send.assert_not_called()
    assert seen_path.read_bytes() == state_before
    output = capsys.readouterr().out
    assert "No unseen matching URLs remained" in output
    assert "Coverage warning: failed=1 partial=0." in output
