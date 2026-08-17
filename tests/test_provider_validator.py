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
from research.validator import (
    build_candidate_company,
    validate_candidate,
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
            config=ProviderConfig(board="old-slug"),
        ),
    )


def test_builds_workday_candidate():
    result = DetectionResult(
        provider=ProviderType.WORKDAY,
        confidence=0.95,
        reason="Workday detected.",
        identifier="Careers",
        config={
            "tenant": "example",
            "cluster": "wd5",
            "board": "Careers",
        },
    )

    candidate = build_candidate_company(
        _company(),
        result,
    )

    assert candidate is not None
    assert candidate.provider.type == ProviderType.WORKDAY
    assert candidate.provider.config.tenant == "example"
    assert candidate.provider.config.cluster == "wd5"
    assert candidate.provider.config.board == "Careers"


def test_original_company_is_not_modified():
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

    candidate = build_candidate_company(
        company,
        result,
    )

    assert candidate is not None

    assert company.provider.type == ProviderType.LEVER
    assert company.provider.config.board == "old-slug"

    assert candidate.provider.type == ProviderType.GREENHOUSE
    assert candidate.provider.config.board == "new-board"


@patch("research.validator._ADAPTERS")
def test_valid_candidate_is_returned(mock_adapters):
    adapter = mock_adapters.get.return_value
    adapter.validate.return_value = True

    result = DetectionResult(
        provider=ProviderType.LEVER,
        confidence=0.95,
        reason="Lever detected.",
        identifier="new-slug",
        config={
            "board": "new-slug",
        },
    )

    candidate = validate_candidate(
        _company(),
        result,
    )

    assert candidate is not None
    assert candidate.provider.type == ProviderType.LEVER
    assert candidate.provider.config.board == "new-slug"

    adapter.validate.assert_called_once()


@patch("research.validator._ADAPTERS")
def test_invalid_candidate_is_rejected(mock_adapters):
    adapter = mock_adapters.get.return_value
    adapter.validate.return_value = False

    result = DetectionResult(
        provider=ProviderType.LEVER,
        confidence=0.95,
        reason="Lever detected.",
        identifier="bad-slug",
        config={
            "board": "bad-slug",
        },
    )

    candidate = validate_candidate(
        _company(),
        result,
    )

    assert candidate is None


def test_unknown_provider_is_rejected():
    result = DetectionResult(
        provider=ProviderType.UNKNOWN,
        confidence=0.0,
        reason="Nothing detected.",
    )

    candidate = build_candidate_company(
        _company(),
        result,
    )

    assert candidate is None