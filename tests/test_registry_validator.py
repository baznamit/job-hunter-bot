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


def test_postman_uses_verified_workday_configuration(
    registry,
):
    company = next(
        company
        for company in registry.companies
        if company.id == "postman"
    )

    assert company.provider.type == ProviderType.WORKDAY
    assert company.provider.status == ProviderStatus.VERIFIED
    assert company.provider.config.tenant == "postman"
    assert company.provider.config.cluster == "wd108"
    assert company.provider.config.board == "careers"


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


def test_duckcreek_uses_verified_workday_configuration(registry):
    matches = [
        company
        for company in registry.companies
        if company.id == "duckcreek"
    ]

    assert len(matches) == 1

    company = matches[0]
    config = company.provider.config

    assert company.name == "Duck Creek Technologies"
    assert company.enabled is True
    assert company.priority == 1
    assert company.provider.type == ProviderType.WORKDAY
    assert company.provider.status == ProviderStatus.VERIFIED

    assert config.tenant == "duckcreek"
    assert config.cluster == "wd1"
    assert config.board == "duckcreekcareers"
    assert config.boards == []


def test_bakerhughes_uses_verified_workday_configuration(registry):
    matches = [
        company
        for company in registry.companies
        if company.id == "bakerhughes"
    ]

    assert len(matches) == 1

    company = matches[0]
    config = company.provider.config

    assert company.name == "Baker Hughes"
    assert company.enabled is True
    assert company.priority == 2
    assert company.provider.type == ProviderType.WORKDAY
    assert company.provider.status == ProviderStatus.VERIFIED

    assert config.tenant == "bakerhughes"
    assert config.cluster == "wd5"
    assert config.board == "BakerHughes"
    assert config.boards == []

    assert "Phenom" in company.notes
    assert "not yet verified" in company.notes


def test_new_workday_companies_have_unique_ids(registry):
    ids = [company.id for company in registry.companies]

    assert ids.count("duckcreek") == 1
    assert ids.count("bakerhughes") == 1
    assert len(ids) == len(set(ids))