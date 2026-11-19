import math
import time
from email.utils import formatdate
from unittest.mock import patch

import pytest

from models.company import Company
from models import Job
from src.filters import JobFilter
from src.providers.eightfold import (
    EightfoldAdapter,
    _retry_after_seconds,
)
from src.providers.exceptions import ProviderTemporaryError

def _company():
    return Company.model_validate(
        {
            "id": "microsoft",
            "name": "Microsoft",
            "category": "SaaS",
            "priority": 3,
            "career_page": (
                "https://apply.careers."
                "microsoft.com/careers"
            ),
            "provider": {
                "type": "eightfold",
                "status": "implemented",
                "config": {
                    "base_url": (
                        "https://apply.careers."
                        "microsoft.com"
                    ),
                    "domain":
                        "microsoft.com",
                },
            },
        }
    )


def _morganstanley_company():
    return Company.model_validate(
        {
            "id": "morganstanley",
            "name": "Morgan Stanley",
            "category": "Banking",
            "priority": 2,
            "career_page": (
                "https://morganstanley.eightfold.ai/careers/search"
            ),
            "provider": {
                "type": "eightfold",
                "status": "implemented",
                "config": {
                    "base_url": (
                        "https://morganstanley.eightfold.ai"
                    ),
                    "domain": "morganstanley.com",
                    "search_location": "India",
                },
            },
        }
    )


def test_eightfold_parses_position():
    adapter = EightfoldAdapter()

    raw = {
        "positions": [
            {
                "id":
                    1970393556960679,
                "displayJobId":
                    "200048252",
                "name": (
                    "Senior Software Engineer "
                    "- Data Platform"
                ),
                "locations": [
                    (
                        "India, Karnataka, "
                        "Bangalore"
                    ),
                    (
                        "India, Telangana, "
                        "Hyderabad"
                    ),
                ],
                "standardizedLocations": [
                    "Bengaluru, KA, IN",
                    "Hyderabad, TS, IN",
                ],
                "postedTs":
                    1786610951,
                "department":
                    "Software Engineering",
                "workLocationOption":
                    "onsite",
                "positionUrl": (
                    "/careers/job/"
                    "1970393556960679"
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

    assert (
        job.id
        == "1970393556960679"
    )

    assert job.title == (
        "Senior Software Engineer "
        "- Data Platform"
    )

    assert job.location == (
        "Bengaluru, KA, IN / "
        "Hyderabad, TS, IN"
    )

    assert job.department == (
        "Software Engineering"
    )

    assert job.posted_at is not None

    assert str(job.url) == (
        "https://apply.careers."
        "microsoft.com/careers/job/"
        "1970393556960679"
    )


def test_morganstanley_uses_india_schema_and_canonical_urls():
    company = _morganstanley_company()
    positions = [
        {
            "id": 549799918919 + index,
            "displayJobId": f"JR{index:06d}",
            "name": "Backend Engineer",
            "standardizedLocations": [
                "Bengaluru, KA, IN",
            ],
            "postedTs": 1793664000,
            "department": "Data & Technology",
            "workLocationOption": "hybrid",
            "positionUrl": (
                f"/careers/job/{549799918919 + index}"
            ),
        }
        for index in range(79)
    ]
    positions[0].update(
        {
            "displayJobId": "PT-JR042853",
            "name": (
                "Java Software Engineer "
                "-Vice President - Parametric"
            ),
            "standardizedLocations": [
                "Mumbai, MH, IN",
            ],
        }
    )
    positions[2].update(
        {
            "standardizedLocations": [
                "Remote - India",
            ],
            "workLocationOption": "remote",
        }
    )
    starts = []

    def request_page(_company, *, start, deadline):
        starts.append(start)
        return positions[start:start + 10], len(positions)

    with (
        patch.object(
            EightfoldAdapter,
            "_request_page",
            side_effect=request_page,
        ),
        patch(
            "src.providers.eightfold.time.sleep"
        ),
    ):
        raw = EightfoldAdapter()._fetch_raw(company)

    jobs = EightfoldAdapter().parse(raw, company)
    job_filter = JobFilter()

    assert starts == list(range(0, 79, 10))
    assert len(jobs) == 79
    assert [job.id for job in jobs] == [
        str(549799918919 + index)
        for index in range(79)
    ]
    assert len({job.id for job in jobs}) == 79
    assert [str(job.url) for job in jobs] == [
        (
            "https://morganstanley.eightfold.ai/"
            f"careers/job/{549799918919 + index}"
        )
        for index in range(79)
    ]
    assert len({str(job.url) for job in jobs}) == 79
    assert jobs[0].location == "Mumbai, MH, IN"
    assert jobs[1].location == "Bengaluru, KA, IN"
    assert jobs[0].title == (
        "Java Software Engineer -Vice President - Parametric"
    )
    assert not job_filter.should_include(jobs[0])
    assert job_filter.should_include(jobs[1])
    assert jobs[2].remote is True
    assert job_filter.should_include(jobs[2])


def test_morganstanley_request_uses_india_location():
    company = _morganstanley_company()
    response = _Response(
        {
            "status": 200,
            "data": {
                "positions": [],
                "count": 0,
            },
        }
    )

    with patch(
        "src.providers.eightfold.requests.get",
        return_value=response,
    ) as mock_get:
        EightfoldAdapter()._request_page(company, start=0)

    assert mock_get.call_args.args[0] == (
        "https://morganstanley.eightfold.ai/api/pcsx/search"
    )
    assert mock_get.call_args.kwargs["params"] == {
        "domain": "morganstanley.com",
        "query": "",
        "location": "India",
        "start": 0,
    }


def test_eightfold_remote_flag():
    adapter = EightfoldAdapter()

    raw = {
        "positions": [
            {
                "id": 123,
                "name": "Software Engineer",
                "standardizedLocations": [
                    "US"
                ],
                "workLocationOption":
                    "remote",
                "positionUrl":
                    "/careers/job/123",
            }
        ]
    }

    jobs = adapter.parse(
        raw,
        _company(),
    )

    assert len(jobs) == 1
    assert jobs[0].remote is True

class _Response:
    def __init__(
        self,
        payload,
    ):
        self._payload = payload
        self.status_code = 200
        self.url = (
            "https://apply.careers."
            "microsoft.com/api/pcsx/search"
        )
        self.headers = {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None

def _payload(
    start: int,
    total: int,
):
    positions = [
        {
            "id": start + index,
            "name":
                f"Software Engineer "
                f"{start + index}",
            "standardizedLocations": [
                "Bengaluru, KA, IN"
            ],
            "positionUrl": (
                f"/careers/job/"
                f"{start + index}"
            ),
        }
        for index in range(
            min(
                10,
                total - start,
            )
        )
    ]

    return {
        "status": 200,
        "data": {
            "positions": positions,
            "count": total,
        },
    }

def test_eightfold_fetches_all_pages():
    company = _company()

    def fake_get(
        url,
        *,
        params,
        headers,
        timeout,
    ):
        return _Response(
            _payload(
                params["start"],
                25,
            )
        )

    with (
        patch(
            "src.providers.eightfold."
            "requests.get",
            side_effect=fake_get,
        ) as mock_get,
        patch(
            "src.providers.eightfold."
            "time.sleep",
        ),
    ):
        raw = (
            EightfoldAdapter()
            ._fetch_raw(company)
        )

    assert len(
        raw["positions"]
    ) == 25

    starts = sorted(
        call.kwargs[
            "params"
        ]["start"]
        for call
        in mock_get.call_args_list
    )

    assert starts == [
        0,
        10,
        20,
    ]


def _positions(ids):
    return [
        {
            "id": position_id,
            "name": f"Software Engineer {position_id}",
            "positionUrl": f"/careers/job/{position_id}",
        }
        for position_id in ids
    ]


def test_eightfold_accepts_empty_inventory_with_zero_total():
    adapter = EightfoldAdapter()

    with patch.object(adapter, "_request_page", return_value=([], 0)):
        raw = adapter._fetch_raw(_company())

    assert raw["positions"] == []


def test_eightfold_rejects_empty_first_page_with_positive_total():
    adapter = EightfoldAdapter()

    with patch.object(adapter, "_request_page", return_value=([], 1)):
        with pytest.raises(
            RuntimeError,
            match="category=empty_page_with_positive_total",
        ):
            adapter._fetch_raw(_company())


def test_eightfold_rejects_total_smaller_than_first_page():
    adapter = EightfoldAdapter()

    with patch.object(
        adapter,
        "_request_page",
        return_value=(_positions(range(2)), 1),
    ):
        with pytest.raises(
            RuntimeError,
            match="category=total_smaller_than_first_page",
        ):
            adapter._fetch_raw(_company())


def test_eightfold_rejects_empty_later_page_before_expected_boundary():
    adapter = EightfoldAdapter()
    responses = [
        (_positions(range(10)), 25),
        ([], 25),
    ]

    with (
        patch.object(adapter, "_request_page", side_effect=responses),
        patch("src.providers.eightfold.time.sleep"),
    ):
        with pytest.raises(
            RuntimeError,
            match="category=unexpected_empty_page",
        ):
            adapter._fetch_raw(_company())


def test_eightfold_rejects_repeated_page_with_no_new_ids():
    adapter = EightfoldAdapter()
    repeated_page = _positions(range(10))

    with (
        patch.object(
            adapter,
            "_request_page",
            side_effect=[
                (repeated_page, 20),
                (repeated_page, 20),
            ],
        ),
        patch("src.providers.eightfold.time.sleep"),
    ):
        with pytest.raises(
            RuntimeError,
            match="category=repeated_page",
        ):
            adapter._fetch_raw(_company())


def test_eightfold_allows_duplicate_ids_when_page_still_progresses():
    adapter = EightfoldAdapter()
    first_page = _positions(range(10))
    second_page = _positions([9, *range(10, 19)])

    with (
        patch.object(
            adapter,
            "_request_page",
            side_effect=[
                (first_page, 20),
                (second_page, 20),
            ],
        ),
        patch("src.providers.eightfold.time.sleep"),
    ):
        raw = adapter._fetch_raw(_company())

    ids = [position["id"] for position in raw["positions"]]
    assert len(ids) == 19
    assert len(set(ids)) == 19


def test_eightfold_count_increase_extends_inventory_boundary():
    adapter = EightfoldAdapter()
    calls = []

    def request_page(_company, *, start, **_kwargs):
        calls.append(start)
        if start == 0:
            return _positions(range(10)), 15
        return _positions(range(10, 20)), 20

    with (
        patch.object(adapter, "_request_page", side_effect=request_page),
        patch("src.providers.eightfold.time.sleep"),
    ):
        raw = adapter._fetch_raw(_company())

    assert calls == [0, 10]
    assert len(raw["positions"]) == 20


def test_eightfold_count_decrease_followed_by_empty_page_fails():
    adapter = EightfoldAdapter()
    calls = []

    def request_page(_company, *, start, **_kwargs):
        calls.append(start)
        if start == 0:
            return _positions(range(10)), 20
        if start == 10:
            return _positions(range(10, 15)), 15
        return [], 15

    with (
        patch.object(adapter, "_request_page", side_effect=request_page),
        patch("src.providers.eightfold.time.sleep"),
    ):
        with pytest.raises(
            RuntimeError,
            match="category=empty_page_after_total_decrease",
        ):
            adapter._fetch_raw(_company())

    assert calls == [0, 10, 15]


def test_eightfold_maximum_page_protection_remains_enforced():
    adapter = EightfoldAdapter()
    calls = []

    def request_page(_company, *, start, **_kwargs):
        calls.append(start)
        return _positions(range(start, start + 10)), 30

    with (
        patch.object(adapter, "_request_page", side_effect=request_page),
        patch("src.providers.eightfold.time.sleep"),
        patch("src.providers.eightfold._MAX_PAGES", 2),
    ):
        with pytest.raises(RuntimeError, match="category=maximum_pages"):
            adapter._fetch_raw(_company())

    assert calls == [0, 10]


@pytest.mark.parametrize(
    "positions, count, category",
    [
        (None, 0, "invalid_positions"),
        ({}, 0, "invalid_positions"),
        ([], True, "invalid_count"),
        ([], -1, "invalid_count"),
    ],
)
def test_eightfold_rejects_malformed_listing_fields(
    positions,
    count,
    category,
):
    adapter = EightfoldAdapter()

    with patch(
        "src.providers.eightfold.requests.get",
        return_value=_Response(
            {
                "data": {
                    "positions": positions,
                    "count": count,
                }
            }
        ),
    ):
        with pytest.raises(RuntimeError, match=f"category={category}"):
            adapter._request_page(_company(), start=0)


@pytest.mark.parametrize(
    "data, category",
    [
        ({"count": 0}, "missing_positions"),
        ({"positions": []}, "missing_count"),
    ],
)
def test_eightfold_requires_positions_and_count(data, category):
    adapter = EightfoldAdapter()

    with patch(
        "src.providers.eightfold.requests.get",
        return_value=_Response({"data": data}),
    ):
        with pytest.raises(RuntimeError, match=f"category={category}"):
            adapter._request_page(_company(), start=0)


def test_eightfold_retries_429():
    company = _company()

    rate_limited = _Response(
        {}
    )

    rate_limited.status_code = 429
    rate_limited.headers = {
        "Retry-After": "1"
    }

    successful = _Response(
        {
            "status": 200,
            "data": {
                "positions": [
                    {
                        "id": 123,
                        "name":
                            "Software Engineer",
                        "positionUrl":
                            "/careers/job/123",
                    }
                ],
                "count": 1,
            },
        }
    )

    with (
        patch(
            "src.providers.eightfold."
            "requests.get",
            side_effect=[
                rate_limited,
                successful,
            ],
        ) as mock_get,
        patch(
            "src.providers.eightfold."
            "time.sleep",
        ) as mock_sleep,
    ):
        positions, total = (
            EightfoldAdapter()
            ._request_page(
                company,
                start=0,
            )
        )

    assert total == 1
    assert len(positions) == 1

    assert mock_get.call_count == 2

    mock_sleep.assert_called_once()


def test_eightfold_uses_configured_search_location():
    company = _company()
    company.provider.config.search_location = (
        "Mumbai"
    )

    response = _Response(
        {
            "status": 200,
            "error": None,
            "data": {
                "positions": [],
                "count": 0,
            },
            "metadata": {},
        }
    )

    with patch(
        "src.providers.eightfold.requests.get",
        return_value=response,
    ) as mock_get:
        EightfoldAdapter()._request_page(
            company,
            start=0,
        )

    params = mock_get.call_args.kwargs["params"]

    assert params["location"] == "Mumbai"


def test_eightfold_defaults_search_location_to_empty():
    company = _company()

    response = _Response(
        {
            "status": 200,
            "error": None,
            "data": {
                "positions": [],
                "count": 0,
            },
            "metadata": {},
        }
    )

    with patch(
        "src.providers.eightfold.requests.get",
        return_value=response,
    ) as mock_get:
        EightfoldAdapter()._request_page(
            company,
            start=0,
        )

    params = mock_get.call_args.kwargs["params"]

    assert params["location"] == ""


class _VirtualClock:
    """Deterministic clock; HTTP calls and sleeps advance it, nothing waits."""

    def __init__(self, latency=0.5):
        self.now = 0.0
        self.latency = latency
        self.sleeps = []
        self.calls = []

    def monotonic(self):
        return self.now

    def sleep(self, delay):
        self.sleeps.append(delay)
        self.now += delay


def _run_virtual(clock, respond, total, action):
    """
    Run action with mocked HTTP. respond(call_number, start) returns None for
    success or a headers dict for HTTP 429.
    """

    def fake_get(url, *, params, headers, timeout):
        start = params["start"]
        clock.calls.append((start, timeout, clock.now))
        clock.now += clock.latency
        throttle = respond(len(clock.calls), start)
        if throttle is None:
            return _Response(_payload(start, total))
        response = _Response({})
        response.status_code = 429
        response.headers = throttle
        return response

    with (
        patch(
            "src.providers.eightfold.requests.get",
            side_effect=fake_get,
        ),
        patch(
            "src.providers.eightfold.time.sleep",
            side_effect=clock.sleep,
        ),
        patch(
            "src.providers.eightfold._now",
            side_effect=clock.monotonic,
        ),
    ):
        return action()


def _fetch_virtual(clock, respond, total):
    return _run_virtual(
        clock,
        respond,
        total,
        lambda: EightfoldAdapter()._fetch_raw(_company()),
    )


def _first_429(headers):
    return lambda call, start: headers if call == 1 else None


@pytest.mark.parametrize(
    "value, expected",
    [
        ("5", 5.0),
        (" 7 ", 7.0),
        ("0", 0.0),
        ("1.5", 1.5),
        (formatdate(1030, usegmt=True), 30.0),
        (formatdate(900, usegmt=True), 0.0),
        ("inf", math.inf),
        ("1e999", math.inf),
        (None, None),
        ("", None),
        ("abc", None),
        ("-5", None),
        ("nan", None),
        ("Wed, 99 Foo 2026 25:61:61 GMT", None),
    ],
)
def test_retry_after_seconds_matrix(value, expected):
    assert _retry_after_seconds(value, now=1000.0) == expected


@pytest.mark.parametrize(
    "header, expected_sleep",
    [
        ("5", 5.5),
        ("0", 0.5),
        ("60", 60.5),
        (None, 15.0),
        ("", 15.0),
        ("abc", 15.0),
        ("-5", 15.0),
        ("nan", 15.0),
    ],
)
def test_429_wait_uses_valid_retry_after_or_default(header, expected_sleep):
    clock = _VirtualClock()
    headers = {} if header is None else {"Retry-After": header}

    positions, total = _run_virtual(
        clock,
        _first_429(headers),
        1,
        lambda: EightfoldAdapter()._request_page(_company(), start=0),
    )

    assert total == 1 and len(positions) == 1
    assert clock.sleeps == [expected_sleep]
    assert len(clock.calls) == 2
    assert clock.now == pytest.approx(expected_sleep + 2 * clock.latency)


def test_429_honors_http_date_retry_after():
    clock = _VirtualClock()
    headers = {"Retry-After": formatdate(time.time() + 30, usegmt=True)}

    _run_virtual(
        clock,
        _first_429(headers),
        1,
        lambda: EightfoldAdapter()._request_page(_company(), start=0),
    )

    assert len(clock.sleeps) == 1
    assert 29.0 <= clock.sleeps[0] <= 31.0
    assert len(clock.calls) == 2


@pytest.mark.parametrize(
    "header",
    [
        "61",
        "3600",
        "inf",
        formatdate(time.time() + 3600, usegmt=True),
    ],
)
def test_retry_after_above_limit_is_deferred_without_waiting(header):
    clock = _VirtualClock()

    with pytest.raises(ProviderTemporaryError) as raised:
        _run_virtual(
            clock,
            _first_429({"Retry-After": header}),
            1,
            lambda: EightfoldAdapter()._request_page(_company(), start=0),
        )

    error = raised.value
    assert error.status == 429
    assert error.category == "rate_limit"
    assert error.deferral_reason == "retry_after_exceeds_limit"
    assert error.retry_after == header
    assert error.retry_after_seconds > 60
    assert clock.sleeps == []
    assert len(clock.calls) == 1
    assert clock.now == clock.latency


def test_retry_after_deferral_is_reported_as_company_failure():
    clock = _VirtualClock()

    with pytest.raises(ProviderTemporaryError):
        _fetch_virtual(clock, _first_429({"Retry-After": "3600"}), 212)

    assert len(clock.calls) == 1


def test_ordinary_429_exhaustion_keeps_retry_count_and_classification():
    clock = _VirtualClock()

    with pytest.raises(ProviderTemporaryError) as raised:
        _fetch_virtual(clock, lambda call, start: {}, 212)

    assert raised.value.category == "rate_limit"
    assert raised.value.deferral_reason is None
    assert len(clock.calls) == 4
    assert clock.sleeps == [15.0, 15.0, 15.0]
    assert clock.now == pytest.approx(47.0)


def test_429_exhaustion_mid_crawl_accepts_no_partial_inventory():
    clock = _VirtualClock()

    with pytest.raises(ProviderTemporaryError) as raised:
        _fetch_virtual(
            clock,
            lambda call, start: {} if start >= 70 else None,
            212,
        )

    assert raised.value.category == "rate_limit"
    assert [call[0] for call in clock.calls].count(70) == 4
    assert len(clock.calls) == 11
    assert clock.now == pytest.approx(67.6)


def test_stable_inventory_request_count_and_pacing_are_unchanged():
    clock = _VirtualClock()

    raw = _fetch_virtual(clock, lambda call, start: None, 212)

    assert len(raw["positions"]) == 212
    assert [call[0] for call in clock.calls] == list(range(0, 212, 10))
    assert all(call[1] == 20 for call in clock.calls)
    assert clock.sleeps.count(15.0) == 4
    assert clock.sleeps.count(0.35) == 17
    assert clock.now == pytest.approx(76.95)


def test_decreasing_total_still_fails_under_virtual_clock():
    clock = _VirtualClock()
    pages = {0: (list(range(10)), 20), 10: (list(range(10, 15)), 15)}

    def fake_get(url, *, params, headers, timeout):
        clock.calls.append((params["start"], timeout, clock.now))
        clock.now += clock.latency
        positions, count = pages.get(params["start"], ([], 15))
        return _Response(
            {
                "data": {
                    "positions": [
                        {"id": i, "name": f"Engineer {i}", "positionUrl": f"/j/{i}"}
                        for i in positions
                    ],
                    "count": count,
                }
            }
        )

    with (
        patch("src.providers.eightfold.requests.get", side_effect=fake_get),
        patch("src.providers.eightfold.time.sleep", side_effect=clock.sleep),
        patch("src.providers.eightfold._now", side_effect=clock.monotonic),
    ):
        with pytest.raises(
            RuntimeError,
            match="category=empty_page_after_total_decrease",
        ):
            EightfoldAdapter()._fetch_raw(_company())

    assert [call[0] for call in clock.calls] == [0, 10, 15]


def test_deadline_expiry_during_backoff_defers_without_sleeping():
    clock = _VirtualClock()

    with patch("src.providers.eightfold._FETCH_BUDGET_SECONDS", 20.0):
        with pytest.raises(ProviderTemporaryError) as raised:
            _fetch_virtual(clock, lambda call, start: {}, 212)

    error = raised.value
    assert error.category == "deferred"
    assert error.deferral_reason == "time_budget"
    assert error.deferred_after_attempt is True
    assert len(clock.calls) == 2
    assert clock.sleeps == [15.0]
    assert clock.now == pytest.approx(16.0)


def test_deadline_expiry_during_pagination_stops_scheduling_and_accepts_nothing():
    clock = _VirtualClock()

    with patch("src.providers.eightfold._FETCH_BUDGET_SECONDS", 20.0):
        with pytest.raises(ProviderTemporaryError) as raised:
            _fetch_virtual(clock, lambda call, start: None, 212)

    assert raised.value.deferral_reason == "time_budget"
    assert raised.value.category == "deferred"
    assert len(clock.calls) < 22
    assert all(started < 20.0 for _, _, started in clock.calls)
    for _, timeout, started in clock.calls:
        assert timeout == pytest.approx(min(20, 20.0 - started))
    # No request was started after the deadline; overshoot is bounded by the
    # single request that was already in flight.
    assert clock.now < 20.0 + clock.latency


def test_in_flight_response_completing_after_deadline_is_used():
    clock = _VirtualClock()

    with patch("src.providers.eightfold._FETCH_BUDGET_SECONDS", 1.2):
        raw = _fetch_virtual(clock, lambda call, start: None, 15)

    assert len(raw["positions"]) == 15
    assert len(clock.calls) == 2
    assert clock.calls[1][1] == pytest.approx(0.35)
    assert clock.now > 1.2


def test_deadline_expired_before_first_request_makes_no_http_attempt():
    clock = _VirtualClock()

    with patch("src.providers.eightfold._FETCH_BUDGET_SECONDS", 0.0):
        with pytest.raises(ProviderTemporaryError) as raised:
            _fetch_virtual(clock, lambda call, start: None, 212)

    assert raised.value.deferral_reason == "time_budget"
    assert raised.value.deferred_after_attempt is False
    assert clock.calls == []


def test_each_company_fetch_gets_its_own_deadline():
    clock = _VirtualClock()
    adapter = EightfoldAdapter()

    with patch("src.providers.eightfold._FETCH_BUDGET_SECONDS", 3.0):
        for _ in range(2):
            raw = _run_virtual(
                clock,
                lambda call, start: None,
                25,
                lambda: adapter._fetch_raw(_company()),
            )
            assert len(raw["positions"]) == 25

    assert len(clock.calls) == 6
    assert clock.now > 3.0


def _item(number, **overrides):
    item = {
        "id": number,
        "name": f"Engineer {number}",
        "positionUrl": f"/careers/job/{number}",
    }
    item.update(overrides)
    return item


def _scripted_fetch(clock, items, *, total_for=None, throttle=None, budget=None):
    """Serve items 10 at a time through fetch_jobs on the virtual clock."""

    def fake_get(url, *, params, headers, timeout):
        start = params["start"]
        clock.calls.append((start, timeout, clock.now))
        clock.now += clock.latency
        headers_429 = throttle(len(clock.calls), start) if throttle else None
        if headers_429 is not None:
            response = _Response({})
            response.status_code = 429
            response.headers = headers_429
            return response
        total = total_for(len(clock.calls)) if total_for else len(items)
        return _Response(
            {"data": {"positions": items[start:start + 10], "count": total}}
        )

    patches = [
        patch("src.providers.eightfold.requests.get", side_effect=fake_get),
        patch("src.providers.eightfold.time.sleep", side_effect=clock.sleep),
        patch("src.providers.eightfold._now", side_effect=clock.monotonic),
    ]
    if budget is not None:
        patches.append(patch("src.providers.eightfold._FETCH_BUDGET_SECONDS", budget))
    for active in patches:
        active.start()
    try:
        return EightfoldAdapter().fetch_jobs(_company())
    finally:
        for active in patches:
            active.stop()


def _accounting(capsys):
    lines = [
        line for line in capsys.readouterr().out.splitlines()
        if " accounting " in line
    ]
    assert len(lines) == 1
    return lines[0], dict(
        part.split("=", 1) for part in lines[0].split() if "=" in part
    )


def test_accounting_stable_inventory_without_duplicates(capsys):
    clock = _VirtualClock()

    jobs = _scripted_fetch(clock, [_item(i) for i in range(1, 213)])

    line, fields = _accounting(capsys)
    assert len(jobs) == 212
    assert len(clock.calls) == 22
    assert fields == {
        "status": "complete", "pages": "22", "raw_records": "212",
        "duplicate_ids": "0", "unique_ids": "212", "parsed": "212",
        "skipped": "0", "skip_reasons": "none", "jobs": "212",
        "unique_urls": "212", "total_first": "212", "total_last": "212",
        "total_min": "212", "total_max": "212",
    }


def test_accounting_counts_duplicate_ids_across_pages(capsys):
    clock = _VirtualClock()
    items = [_item(i) for i in range(1, 31)]
    items[12] = dict(items[2])
    items[25] = dict(items[2])

    jobs = _scripted_fetch(clock, items)

    _, fields = _accounting(capsys)
    assert [job.id for job in jobs] == [str(i) for i in range(1, 31) if i not in (13, 26)]
    assert fields["raw_records"] == "30"
    assert fields["duplicate_ids"] == "2"
    assert fields["unique_ids"] == "28"
    assert fields["jobs"] == "28"


def test_accounting_reports_parse_skips_by_safe_category_only(capsys):
    clock = _VirtualClock()
    items = [_item(i) for i in range(1, 21)]
    items[1] = _item(2, name="")
    items[2] = _item(3, name=None)
    items[3] = _item(4, positionUrl="")
    items[4] = _item(5, name="Secret Title", positionUrl=None)

    jobs = _scripted_fetch(clock, items)

    line, fields = _accounting(capsys)
    assert [job.id for job in jobs] == [str(i) for i in range(1, 21) if i not in (2, 3, 4, 5)]
    assert fields["raw_records"] == "20"
    assert fields["parsed"] == "16" and fields["skipped"] == "4"
    assert fields["skip_reasons"] == "missing_title:2,missing_url:2"
    assert "Secret Title" not in line
    assert "careers/job" not in line


def test_parse_skip_categories_for_malformed_records():
    adapter = EightfoldAdapter()
    jobs, skipped = adapter._parse_with_skips(
        {"positions": [
            "text", None, {"name": "x", "positionUrl": "/p"},
            _item(1, name=""), _item(2, positionUrl=""), _item(3),
        ]},
        _company(),
    )

    assert [job.id for job in jobs] == ["3"]
    assert skipped == {
        "invalid_record": 2, "missing_id": 1, "missing_title": 1, "missing_url": 1,
    }
    assert [job.id for job in adapter.parse({"positions": [_item(3)]}, _company())] == ["3"]


def test_accounting_does_not_change_returned_jobs_or_urls():
    items = [_item(i, name=f" Engineer {i} ") for i in range(1, 26)]
    adapter = EightfoldAdapter()
    clock = _VirtualClock()

    via_fetch = _scripted_fetch(clock, items)
    raw = {"positions": items}
    via_parse = adapter.parse(raw, _company())

    assert [(job.id, job.title, str(job.url)) for job in via_fetch] == [
        (job.id, job.title, str(job.url)) for job in via_parse
    ]
    assert str(via_fetch[0].url) == "https://apply.careers.microsoft.com/careers/job/1"


def test_accounting_tracks_total_changes_when_inventory_grows(capsys):
    clock = _VirtualClock()
    items = [_item(i) for i in range(1, 36)]

    jobs = _scripted_fetch(
        clock, items, total_for=lambda call: 30 if call < 3 else 35,
    )

    _, fields = _accounting(capsys)
    assert len(jobs) == 35
    assert fields["total_first"] == "30" and fields["total_last"] == "35"
    assert fields["total_min"] == "30" and fields["total_max"] == "35"
    assert fields["pages"] == "4"


def test_accounting_on_decreasing_total_failure_keeps_failure_and_never_succeeds(capsys):
    clock = _VirtualClock()
    items = [_item(i) for i in range(1, 16)]

    with pytest.raises(
        RuntimeError, match="category=empty_page_after_total_decrease",
    ):
        _scripted_fetch(
            clock, items, total_for=lambda call: 20 if call < 2 else 15,
        )

    _, fields = _accounting(capsys)
    assert fields["status"] == "failed"
    assert "jobs" not in fields and "parsed" not in fields
    assert fields["pages"] == "3" and fields["raw_records"] == "15"
    assert fields["total_first"] == "20" and fields["total_last"] == "15"
    assert fields["total_min"] == "15" and fields["total_max"] == "20"
    assert [call[0] for call in clock.calls] == [0, 10, 15]


def test_accounting_on_429_exhaustion_preserves_classification_and_requests(capsys):
    clock = _VirtualClock()
    items = [_item(i) for i in range(1, 213)]

    with pytest.raises(ProviderTemporaryError) as raised:
        _scripted_fetch(
            clock, items, throttle=lambda call, start: {} if start >= 70 else None,
        )

    _, fields = _accounting(capsys)
    assert raised.value.category == "rate_limit"
    assert len(clock.calls) == 11
    assert fields["status"] == "failed"
    assert fields["pages"] == "7" and fields["raw_records"] == "70"


def test_accounting_on_deadline_expiry_preserves_classification(capsys):
    clock = _VirtualClock()
    items = [_item(i) for i in range(1, 213)]

    with pytest.raises(ProviderTemporaryError) as raised:
        _scripted_fetch(clock, items, budget=20.0)

    _, fields = _accounting(capsys)
    assert raised.value.category == "deferred"
    assert raised.value.deferral_reason == "time_budget"
    assert fields["status"] == "failed"
    assert int(fields["pages"]) == len(clock.calls)


def test_accounting_failed_on_malformed_record_keeps_existing_category(capsys):
    clock = _VirtualClock()
    items = [_item(i) for i in range(1, 11)]
    items[4] = _item(5, id=None)

    with pytest.raises(RuntimeError, match="category=missing_position_id"):
        _scripted_fetch(clock, items)

    _, fields = _accounting(capsys)
    assert fields["status"] == "failed"
    assert fields["pages"] == "1" and fields["raw_records"] == "10"
    assert fields["unique_ids"] == "4"
    assert len(clock.calls) == 1


def test_accounting_marks_parse_failure_and_reraises(capsys):
    clock = _VirtualClock()

    with patch.object(
        EightfoldAdapter, "_parse_with_skips", side_effect=ValueError("bad"),
    ):
        with pytest.raises(ValueError, match="bad"):
            _scripted_fetch(clock, [_item(1)])

    _, fields = _accounting(capsys)
    assert fields["status"] == "parse_failed"
    assert "jobs" not in fields


def test_accounting_counts_reconcile_on_success(capsys):
    clock = _VirtualClock()
    items = [_item(i) for i in range(1, 41)]
    items[7] = dict(items[1])
    items[20] = dict(items[1])
    items[10] = _item(11, name="")
    items[30] = _item(31, positionUrl=None)
    items[33] = _item(34, positionUrl="/careers/job/1")

    jobs = _scripted_fetch(clock, items)

    _, fields = _accounting(capsys)
    raw_records = int(fields["raw_records"])
    assert raw_records == 40
    assert raw_records == int(fields["unique_ids"]) + int(fields["duplicate_ids"])
    # Parser input is exactly the deduplicated records.
    assert int(fields["parsed"]) + int(fields["skipped"]) == int(fields["unique_ids"])
    assert int(fields["parsed"]) == int(fields["jobs"]) == len(jobs)
    assert int(fields["unique_urls"]) == len({str(job.url) for job in jobs})
    assert int(fields["unique_urls"]) == len(jobs) - 1
    # Output order is the ATS order with the first duplicate occurrence kept.
    ids = [job.id for job in jobs]
    assert ids == [
        str(i) for i in range(1, 41) if i not in (8, 21, 11, 31)
    ]


def test_each_record_is_parsed_exactly_once_for_diagnostics():
    clock = _VirtualClock()
    adapter = EightfoldAdapter()
    original = EightfoldAdapter._parse_with_skips
    inputs = []

    def spy(self, raw, company):
        inputs.append(len(raw["positions"]))
        return original(self, raw, company)

    with patch.object(EightfoldAdapter, "_parse_with_skips", spy):
        with patch("src.providers.eightfold.Job", wraps=Job) as job_class:
            patches = [
                patch("src.providers.eightfold.requests.get", side_effect=lambda url, *, params, headers, timeout: _Response(
                    {"data": {"positions": [_item(i) for i in range(1, 16)][params["start"]:params["start"] + 10], "count": 15}}
                )),
                patch("src.providers.eightfold.time.sleep", side_effect=clock.sleep),
            ]
            for active in patches:
                active.start()
            try:
                jobs = adapter.fetch_jobs(_company())
            finally:
                for active in patches:
                    active.stop()

    assert len(jobs) == 15
    assert inputs == [15]
    assert job_class.call_count == 15


def test_failing_diagnostic_print_never_masks_or_fails_a_fetch():
    real_print = print

    def flaky_print(*args, **kwargs):
        if args and " accounting " in str(args[0]):
            raise OSError("stdout closed")
        return real_print(*args, **kwargs)

    clock = _VirtualClock()

    with patch("builtins.print", side_effect=flaky_print):
        jobs = _scripted_fetch(clock, [_item(i) for i in range(1, 13)])
        assert len(jobs) == 12

        with pytest.raises(
            RuntimeError, match="category=empty_page_after_total_decrease",
        ):
            _scripted_fetch(
                _VirtualClock(),
                [_item(i) for i in range(1, 16)],
                total_for=lambda call: 20 if call < 2 else 15,
            )

        with pytest.raises(ValueError, match="bad"):
            with patch.object(
                EightfoldAdapter, "_parse_with_skips", side_effect=ValueError("bad"),
            ):
                _scripted_fetch(_VirtualClock(), [_item(1)])

