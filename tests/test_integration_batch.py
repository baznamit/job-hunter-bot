from types import SimpleNamespace
from unittest.mock import patch

from research.company_probe import (
    _integration_summary,
    _probe_existing_workday,
)


def _job(job_id, title, location):
    return SimpleNamespace(
        id=job_id,
        title=title,
        location=location,
        url=f"https://example.com/job/{job_id}",
    )


def test_summary_accepts_unique_jobs():
    jobs = [
        _job(
            "1",
            "Java Backend Engineer",
            "Mumbai, India",
        ),
        _job(
            "2",
            "Full Stack Developer",
            "Bengaluru, India",
        ),
    ]

    assert _integration_summary(
        "TEST", jobs
    ) is True


def test_summary_rejects_duplicate_ids():
    jobs = [
        _job("1", "Java Engineer", "Mumbai"),
        _job("1", "Java Developer", "Bengaluru"),
    ]

    assert _integration_summary(
        "TEST", jobs
    ) is False


def test_existing_workday_probe_uses_registry_company():
    company = SimpleNamespace(
        id="browserstack",
        provider=SimpleNamespace(
            type=SimpleNamespace(value="workday")
        ),
        enabled=True,
    )

    company.model_copy = lambda deep: company

    registry = SimpleNamespace(
        companies=[company]
    )

    with patch(
        "src.providers.workday.WorkdayAdapter.fetch_jobs",
        return_value=[
            _job(
                "123",
                "Java Engineer",
                "Mumbai, India",
            )
        ],
    ) as mock_fetch:
        assert _probe_existing_workday(
            "browserstack", registry
        ) is True

    mock_fetch.assert_called_once()
