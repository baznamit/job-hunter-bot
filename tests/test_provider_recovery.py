from datetime import (
    datetime,
    timedelta,
    timezone,
)
from unittest.mock import MagicMock
from unittest.mock import patch

from models import DetectionResult
from models.company import (
    Company,
    CompanyCategory,
    Provider,
    ProviderConfig,
    ProviderStatus,
    ProviderType,
)
from src.main import (
    _fetch_jobs_with_recovery,
    _recover_stale_provider,
)


def _company() -> Company:
    return Company(
        id="test-company",
        name="Test Company",
        category=CompanyCategory.SAAS,
        priority=1,
        career_page="https://example.com/careers",
        provider=Provider(
            type=ProviderType.LEVER,
            status=ProviderStatus.PARTIAL,
            config=ProviderConfig(
                board="old-slug",
            ),
        ),
    )


@patch("src.main.validate_candidate")
@patch("src.main.discover_provider")
def test_recovery_returns_valid_candidate(
    mock_discover,
    mock_validate,
):
    company = _company()

    result = DetectionResult(
        provider=ProviderType.GREENHOUSE,
        confidence=0.95,
        reason="Greenhouse detected.",
        identifier="new-board",
        config={
            "board": "new-board",
        },
    )

    recovered = company.model_copy(
        update={
            "provider": Provider(
                type=ProviderType.GREENHOUSE,
                status=ProviderStatus.PARTIAL,
                config=ProviderConfig(
                    board="new-board",
                ),
            )
        },
        deep=True,
    )

    mock_discover.return_value = result
    mock_validate.return_value = recovered

    candidate = _recover_stale_provider(company)

    assert candidate is not None
    assert candidate.provider.type == ProviderType.GREENHOUSE
    assert candidate.provider.config.board == "new-board"

    mock_discover.assert_called_once_with(company)
    mock_validate.assert_called_once_with(
        company,
        result,
    )


@patch("src.main.validate_candidate")
@patch("src.main.discover_provider")
def test_recovery_rejects_invalid_candidate(
    mock_discover,
    mock_validate,
):
    company = _company()

    result = DetectionResult(
        provider=ProviderType.GREENHOUSE,
        confidence=0.95,
        reason="Greenhouse detected.",
        identifier="bad-board",
        config={
            "board": "bad-board",
        },
    )

    mock_discover.return_value = result
    mock_validate.return_value = None

    candidate = _recover_stale_provider(company)

    assert candidate is None


@patch("src.main.discover_provider")
def test_recovery_handles_unknown_provider(
    mock_discover,
):
    mock_discover.return_value = DetectionResult(
        provider=ProviderType.UNKNOWN,
        confidence=0.0,
        reason="Nothing detected.",
    )

    candidate = _recover_stale_provider(
        _company()
    )

    assert candidate is None


@patch("src.main.discover_provider")
def test_recovery_handles_discovery_exception(
    mock_discover,
):
    mock_discover.side_effect = RuntimeError(
        "career page unavailable"
    )

    candidate = _recover_stale_provider(
        _company()
    )

    assert candidate is None


def test_known_stale_provider_is_not_fetched_during_cooldown():
    company = _company()

    adapter = MagicMock()
    recovery_store = MagicMock()

    retry_at = (
        datetime.now(timezone.utc)
        + timedelta(hours=12)
    )

    recovery_store.should_attempt.return_value = (
        False,
        retry_at,
    )

    jobs = _fetch_jobs_with_recovery(
        company,
        adapter,
        recovery_store,
        {
            "base_cooldown_hours": 6,
            "max_cooldown_hours": 72,
        },
    )

    assert jobs is None

    adapter.fetch_jobs.assert_not_called()

    recovery_store.should_attempt.assert_called_once_with(
        company.id
    )


def test_provider_is_retried_after_recovery_cooldown():
    company = _company()

    adapter = MagicMock()

    expected_jobs = []

    adapter.fetch_jobs.return_value = (
        expected_jobs
    )

    recovery_store = MagicMock()

    recovery_store.should_attempt.return_value = (
        True,
        None,
    )

    jobs = _fetch_jobs_with_recovery(
        company,
        adapter,
        recovery_store,
        {
            "base_cooldown_hours": 6,
            "max_cooldown_hours": 72,
        },
    )

    assert jobs == expected_jobs

    adapter.fetch_jobs.assert_called_once_with(
        company
    )

    recovery_store.clear.assert_called_once_with(
        company.id
    )