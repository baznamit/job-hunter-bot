from unittest.mock import patch

import pytest

from models.company import Company
from src.providers.eightfold import (
    EightfoldAdapter,
)

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

