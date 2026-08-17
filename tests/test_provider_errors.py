import pytest
import requests

from models.company import (
    Company,
    CompanyCategory,
    Provider,
    ProviderConfig,
    ProviderStatus,
    ProviderType,
)
from src.providers.exceptions import (
    ProviderNotFoundError,
    ProviderTemporaryError,
)
from src.providers.lever import LeverAdapter


def _company() -> Company:
    return Company(
        id="test",
        name="Test Co",
        category=CompanyCategory.SAAS,
        priority=1,
        career_page="https://example.com/careers",
        provider=Provider(
            type=ProviderType.LEVER,
            status=ProviderStatus.PARTIAL,
            config=ProviderConfig(board="test"),
        ),
    )


def _response(status_code: int) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response.url = "https://api.example.com/jobs"
    return response


def test_404_is_classified_as_stale_mapping():
    adapter = LeverAdapter()

    with pytest.raises(ProviderNotFoundError):
        adapter._check_response(
            _response(404),
            _company(),
        )

def test_422_is_classified_as_stale_mapping():
    adapter = LeverAdapter()

    with pytest.raises(ProviderNotFoundError):
        adapter._check_response(
            _response(422),
            _company(),
        )

def test_429_is_classified_as_temporary_failure():
    adapter = LeverAdapter()

    with pytest.raises(ProviderTemporaryError):
        adapter._check_response(
            _response(429),
            _company(),
        )


def test_500_is_classified_as_temporary_failure():
    adapter = LeverAdapter()

    with pytest.raises(ProviderTemporaryError):
        adapter._check_response(
            _response(500),
            _company(),
        )


def test_200_does_not_raise():
    adapter = LeverAdapter()

    adapter._check_response(
        _response(200),
        _company(),
    )