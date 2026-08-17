from unittest.mock import patch

from models import DetectionResult, PageSnapshot
from models.company import (
    Company,
    CompanyCategory,
    Provider,
    ProviderConfig,
    ProviderStatus,
    ProviderType,
)
from research.discovery import discover_provider


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
            config=ProviderConfig(board="old-slug"),
        ),
    )


def _snapshot() -> PageSnapshot:
    return PageSnapshot(
        original_url="https://example.com/careers",
        final_url="https://example.com/careers",
        status_code=200,
        html="<html></html>",
        headers={},
    )


@patch("research.discovery.detect_provider")
@patch("research.discovery.fetch_page")
def test_page_detection_is_used_first(
    mock_fetch,
    mock_detect,
):
    mock_fetch.return_value = _snapshot()

    mock_detect.return_value = DetectionResult(
        provider=ProviderType.GREENHOUSE,
        confidence=0.95,
        reason="Greenhouse URL found.",
        identifier="test-company",
    )

    with patch("research.discovery.probe_provider") as mock_probe:
        result = discover_provider(_company())

    assert result.provider == ProviderType.GREENHOUSE
    assert result.identifier == "test-company"

    mock_probe.assert_not_called()


@patch("research.discovery.probe_provider")
@patch("research.discovery.detect_provider")
@patch("research.discovery.fetch_page")
def test_api_probe_is_fallback(
    mock_fetch,
    mock_detect,
    mock_probe,
):
    mock_fetch.return_value = _snapshot()

    mock_detect.return_value = DetectionResult(
        provider=ProviderType.UNKNOWN,
        confidence=0.0,
        reason="Nothing found.",
    )

    mock_probe.return_value = DetectionResult(
        provider=ProviderType.ASHBY,
        confidence=0.85,
        reason="API responded.",
        identifier="test-company",
    )

    result = discover_provider(_company())

    assert result.provider == ProviderType.ASHBY
    assert result.identifier == "test-company"

    mock_probe.assert_called_once()


@patch("research.discovery.probe_provider")
@patch("research.discovery.fetch_page")
def test_probe_still_runs_when_career_page_fetch_fails(
    mock_fetch,
    mock_probe,
):
    mock_fetch.side_effect = RuntimeError("network error")

    mock_probe.return_value = DetectionResult(
        provider=ProviderType.LEVER,
        confidence=0.85,
        reason="API responded.",
        identifier="test-company",
    )

    result = discover_provider(_company())

    assert result.provider == ProviderType.LEVER
    assert result.identifier == "test-company"

    mock_probe.assert_called_once()