"""
Validate ATS configurations discovered by the research system.

Discovery and validation are intentionally separate:

    discover -> candidate configuration
             -> validate against real ATS API
             -> usable configuration

A candidate is considered valid only when the corresponding provider
adapter can successfully fetch from it.
"""

from pydantic import ValidationError

from models import DetectionResult
from models.company import (
    Company,
    CompanyRegistry,
    Provider,
    ProviderConfig,
    ProviderStatus,
    ProviderType,
)
from src.providers import (
    AshbyAdapter,
    GreenhouseAdapter,
    LeverAdapter,
    WorkdayAdapter,
)
from src.providers.exceptions import ProviderError


_ADAPTERS = {
    ProviderType.GREENHOUSE: GreenhouseAdapter(),
    ProviderType.LEVER: LeverAdapter(),
    ProviderType.ASHBY: AshbyAdapter(),
    ProviderType.WORKDAY: WorkdayAdapter(),
}


def _candidate_config(result: DetectionResult) -> dict[str, str]:
    """
    Convert a DetectionResult into provider configuration.

    Structured config is preferred. `identifier` remains as a fallback
    for older detectors/probers.
    """

    if result.config:
        return dict(result.config)

    if result.identifier is None:
        return {}

    if result.provider in (
        ProviderType.GREENHOUSE,
        ProviderType.LEVER,
    ):
        return {"board": result.identifier}

    if result.provider is ProviderType.ASHBY:
        return {"organization": result.identifier}

    return {}


def build_candidate_company(
    company: Company,
    result: DetectionResult,
) -> Company | None:
    """
    Return a copy of Company using the discovered provider configuration.

    The original Company object is never modified.
    """

    adapter = _ADAPTERS.get(result.provider)

    if adapter is None:
        return None

    config = _candidate_config(result)

    if not config:
        return None

    try:
        provider_config = ProviderConfig(**config)

        provider = Provider(
            type=result.provider,
            status=ProviderStatus.PARTIAL,
            config=provider_config,
        )

        return company.model_copy(
            update={"provider": provider},
            deep=True,
        )

    except ValidationError:
        return None


def validate_candidate(
    company: Company,
    result: DetectionResult,
) -> Company | None:
    """
    Validate a discovered ATS configuration against the real provider.

    Returns a temporary Company containing the discovered provider
    configuration when validation succeeds.

    Returns None when:
    - provider isn't implemented
    - discovered config is incomplete
    - ATS endpoint rejects the candidate
    - network/provider validation fails

    This function never modifies companies.json.
    """

    candidate = build_candidate_company(company, result)

    if candidate is None:
        return None

    adapter = _ADAPTERS.get(candidate.provider.type)

    if adapter is None:
        return None

    try:
        valid = adapter.validate(candidate)
    except ProviderError:
        return None
    except Exception:
        return None

    if not valid:
        return None

    return candidate

def validate_registry(registry: CompanyRegistry) -> None:
    """
    Validate provider configuration for every company in the registry.

    This performs structural validation only. It does not make network
    requests to ATS providers.

    Raises ValueError when a company has an invalid or incomplete
    provider configuration.
    """

    for company in registry.companies:
        provider = company.provider
        config = provider.config

        # Companies still awaiting ATS research are allowed to have
        # incomplete provider configuration.
        if provider.status == ProviderStatus.RESEARCH_PENDING:
            continue

        # Unknown providers are also allowed while research is pending
        # or when no supported ATS has been identified.
        if provider.type == ProviderType.UNKNOWN:
            continue

        if provider.type in (
            ProviderType.GREENHOUSE,
            ProviderType.LEVER,
        ):
            if not config.board:
                raise ValueError(
                    f"{company.name}: {provider.type.value} "
                    "provider requires config.board"
                )

        elif provider.type == ProviderType.ASHBY:
            if not config.organization:
                raise ValueError(
                    f"{company.name}: Ashby provider requires "
                    "config.organization"
                )

        elif provider.type == ProviderType.WORKDAY:
            missing = []

            if not config.tenant:
                missing.append("tenant")

            if not config.cluster:
                missing.append("cluster")

            if not config.board:
                missing.append("board")

            if missing:
                raise ValueError(
                    f"{company.name}: Workday provider is missing "
                    f"config fields: {', '.join(missing)}"
                )