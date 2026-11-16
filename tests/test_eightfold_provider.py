import math
import time
from email.utils import formatdate
from unittest.mock import patch

import pytest

from models.company import Company
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

