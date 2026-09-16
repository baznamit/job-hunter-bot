import pytest

from models.company import (
    ProviderStatus,
    ProviderType,
)
from research.loader import load_registry
from research.validator import validate_registry


@pytest.fixture
def registry():
    return load_registry()


def test_registry_is_valid(registry):
    validate_registry(registry)


def test_freshworks_uses_smartrecruiters(
    registry,
):
    company = next(
        company
        for company
        in registry.companies
        if company.id
        == "freshworks"
    )

    assert (
        company.provider.type
        == ProviderType.SMARTRECRUITERS
    )

    assert (
        company.provider.config.
        company_identifier
        == "Freshworks"
    )


def test_navi_does_not_use_unrelated_ashby_board(
    registry,
):
    company = next(
        company
        for company
        in registry.companies
        if company.id == "navi"
    )

    assert (
        company.provider.type
        == ProviderType.UNKNOWN
    )

    assert (
        company.provider.status
        == ProviderStatus.RESEARCH_PENDING
    )


def test_weatherford_uses_oracle_cx(
    registry,
):
    company = next(
        company
        for company
        in registry.companies
        if company.id
        == "weatherford"
    )

    assert (
        company.provider.type
        == ProviderType.ORACLE
    )

    config = (
        company.provider.config
    )

    assert config.host == (
        "fa-exmi-saasfaprod1."
        "fa.ocs.oraclecloud.com"
    )

    assert len(
        config.sites
    ) == 1

    site = config.sites[0]

    assert (
        site.site_number
        == "CX_1"
    )

    assert (
        site.site_path
        == "CX_1"
    )

    assert site.enabled is True


def test_weatherford_uses_oracle_cx(
    registry,
):
    company = next(
        company
        for company
        in registry.companies
        if company.id
        == "weatherford"
    )

    assert (
        company.provider.type
        == ProviderType.ORACLE
    )

    config = (
        company.provider.config
    )

    assert config.host == (
        "fa-exmi-saasfaprod1."
        "fa.ocs.oraclecloud.com"
    )

    assert len(
        config.sites
    ) == 1

    site = config.sites[0]

    assert (
        site.site_number
        == "CX_1"
    )

    assert (
        site.site_path
        == "CX_1"
    )

    assert site.enabled is True