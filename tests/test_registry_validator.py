import pytest

from models.company import (
    ProviderStatus,
    ProviderType,
)
from research.loader import load_registry
from research.validator import validate_registry
from src.main import _ADAPTERS
from src.providers.eightfold import EightfoldAdapter


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


def test_ey_uses_successfactors_city_scoped_search(registry):
    company = next(
        company
        for company in registry.companies
        if company.id == "ey"
    )

    assert company.enabled
    assert company.provider.type == ProviderType.SUCCESSFACTORS
    assert company.provider.status == ProviderStatus.VERIFIED
    assert company.provider.config.base_url == "https://careers.ey.com"
    assert company.provider.config.listing_path == "/ey/search/"
    assert company.provider.config.search_location_param == (
        "optionsFacetsDD_city"
    )
    assert company.provider.config.search_locations == [
        "Mumbai",
        "Bengaluru",
        "Bangalore",
    ]
    assert company.provider.config.search_params[
        "optionsFacetsDD_country"
    ] == "IN"


def test_navi_uses_verified_turbohire_board(
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
        == ProviderType.TURBOHIRE
    )

    assert (
        company.provider.status
        == ProviderStatus.VERIFIED
    )

    assert (
        company.provider.config.base_url
        == "https://navi.turbohire.co"
    )

    assert (
        company.provider.config.organization
        == "navi"
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


def test_cisco_uses_verified_workday_configuration(registry):
    matches = [
        company
        for company in registry.companies
        if company.id == "cisco"
    ]

    assert len(matches) == 1

    company = matches[0]
    config = company.provider.config

    assert company.name == "Cisco"
    assert company.enabled is True
    assert company.provider.type == ProviderType.WORKDAY
    assert company.provider.status == ProviderStatus.VERIFIED
    assert config.tenant == "cisco"
    assert config.cluster == "wd5"
    assert config.board == "Cisco_Careers"
    assert config.boards == []
    assert company.locations == []
    assert company.roles == []


def test_morganstanley_uses_verified_eightfold_configuration(registry):
    matches = [
        company
        for company in registry.companies
        if company.id == "morganstanley"
    ]

    assert len(matches) == 1

    company = matches[0]
    config = company.provider.config

    assert company.name == "Morgan Stanley"
    assert company.enabled is True
    assert company.priority == 2
    assert company.category.value == "Banking"
    assert company.provider.type == ProviderType.EIGHTFOLD
    assert company.provider.status == ProviderStatus.IMPLEMENTED
    assert str(company.career_page) == (
        "https://morganstanley.eightfold.ai/careers/search"
    )
    assert config.base_url == "https://morganstanley.eightfold.ai"
    assert config.domain == "morganstanley.com"
    assert config.search_location == "India"
    assert company.supports_remote is False
    assert isinstance(
        _ADAPTERS[company.provider.type],
        EightfoldAdapter,
    )


def test_imc_uses_verified_greenhouse_configuration(registry):
    company = next(
        company
        for company in registry.companies
        if company.id == "imc"
    )

    assert company.name == "IMC Trading"
    assert company.enabled is True
    assert company.priority == 1
    assert company.category.value == "FinTech"
    assert company.provider.type == ProviderType.GREENHOUSE
    assert company.provider.status == ProviderStatus.VERIFIED
    assert company.provider.config.board == "imc"
    assert str(company.career_page) == (
        "https://www.imc.com/in/search-careers"
    )


def test_microsoft_eightfold_remains_disabled(registry):
    company = next(
        company
        for company in registry.companies
        if company.id == "microsoft"
    )

    assert company.provider.type == ProviderType.EIGHTFOLD
    assert company.enabled is False
    assert company.provider.config.domain == "microsoft.com"


def test_new_workday_companies_have_unique_ids(registry):
    ids = [company.id for company in registry.companies]

    assert ids.count("duckcreek") == 1
    assert ids.count("bakerhughes") == 1
    assert len(ids) == len(set(ids))
