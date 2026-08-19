from unittest.mock import Mock, patch

import pytest

from models.company import (
    Company,
    CompanyCategory,
    Provider,
    ProviderConfig,
    ProviderStatus,
    ProviderType,
)
from src.providers.oracle import OracleAdapter


def _company() -> Company:
    return Company(
        id="test-oracle",
        name="Test Oracle Co",
        category=CompanyCategory.BANKING,
        priority=1,
        career_page="https://example.com/careers",
        provider=Provider(
            type=ProviderType.ORACLE,
            status=ProviderStatus.PARTIAL,
            config=ProviderConfig(
                host="example.fa.oraclecloud.com",
                sites=[
                    {
                        "site_number": "CX_1",
                        "site_path": "careers",
                    }
                ],
            ),
        ),
    )


def _response(
    jobs,
    total,
):
    response = Mock()
    response.status_code = 200
    response.url = (
        "https://example.fa.oraclecloud.com/"
        "hcmRestApi/resources/latest/"
        "recruitingCEJobRequisitions"
    )
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "items": [
            {
                "TotalJobsCount": total,
                "requisitionList": jobs,
            }
        ]
    }
    return response


@patch("src.providers.oracle.requests.get")
def test_oracle_paginates_using_finder_offset(
    mock_get,
):
    first_page = [
        {
            "Id": str(i),
            "Title": f"Job {i}",
            "PrimaryLocation": "Bengaluru",
        }
        for i in range(200)
    ]

    second_page = [
        {
            "Id": str(i),
            "Title": f"Job {i}",
            "PrimaryLocation": "Bengaluru",
        }
        for i in range(200, 250)
    ]

    mock_get.side_effect = [
        _response(first_page, 250),
        _response(second_page, 250),
    ]

    jobs = OracleAdapter().fetch_jobs(
        _company()
    )

    assert len(jobs) == 250
    assert mock_get.call_count == 2

    first_finder = (
        mock_get.call_args_list[0]
        .kwargs["params"]["finder"]
    )

    second_finder = (
        mock_get.call_args_list[1]
        .kwargs["params"]["finder"]
    )

    assert "limit=200" in first_finder
    assert "offset=0" in first_finder

    assert "limit=200" in second_finder
    assert "offset=200" in second_finder


@patch("src.providers.oracle.requests.get")
def test_oracle_detects_repeated_page(
    mock_get,
):
    page = [
        {
            "Id": str(i),
            "Title": f"Job {i}",
            "PrimaryLocation": "Bengaluru",
        }
        for i in range(200)
    ]

    mock_get.side_effect = [
        _response(page, 400),
        _response(page, 400),
    ]

    with pytest.raises(
        RuntimeError,
        match="pagination stalled",
    ):
        OracleAdapter().fetch_jobs(
            _company()
        )


@patch("src.providers.oracle.requests.get")
def test_oracle_validate_uses_single_record(
    mock_get,
):
    mock_get.return_value = _response(
        [
            {
                "Id": "123",
                "Title": "Software Engineer",
            }
        ],
        100,
    )

    assert OracleAdapter().validate(
        _company()
    )

    finder = (
        mock_get.call_args
        .kwargs["params"]["finder"]
    )

    assert "limit=1" in finder
    assert "offset=0" in finder

@patch("src.providers.oracle.requests.get")
def test_oracle_stops_at_total_even_with_duplicate_ids(
    mock_get,
):
    first_page = [
        {
            "Id": str(i),
            "Title": f"Job {i}",
            "PrimaryLocation": "Bengaluru",
        }
        for i in range(200)
    ]

    # One duplicate from page 1, plus 49 new jobs.
    second_page = [
        {
            "Id": "199",
            "Title": "Job 199",
            "PrimaryLocation": "Bengaluru",
        }
    ] + [
        {
            "Id": str(i),
            "Title": f"Job {i}",
            "PrimaryLocation": "Bengaluru",
        }
        for i in range(200, 249)
    ]

    mock_get.side_effect = [
        _response(first_page, 250),
        _response(second_page, 250),
    ]

    jobs = OracleAdapter().fetch_jobs(
        _company()
    )

    # Oracle reported 250 positions, but one requisition was duplicated.
    assert len(jobs) == 249

    # Most importantly, don't request a third page trying to make the
    # unique-ID count reach TotalJobsCount.
    assert mock_get.call_count == 2