"""
research.discovery
------------------
Reusable ATS discovery service.

Given a Company, attempts to determine its current ATS provider and
provider identifier.

Discovery strategy:

1. Fetch the company's official career page.
2. Inspect the page for known ATS signatures.
3. If page detection fails, probe supported ATS APIs using company
   slug candidates.

This module does not modify companies.json. It only discovers and
returns a candidate provider configuration.
"""

from models import DetectionResult
from models.company import Company, ProviderType
from research.detectors import detect_provider
from research.fetcher import fetch_page
from research.logger import get_logger
from research.prober import probe_provider

log = get_logger(__name__)


def discover_provider(company: Company) -> DetectionResult:
    """
    Discover the ATS currently used by a company.

    The company's official career page is treated as the primary source.
    API probing is used as a fallback for JavaScript-rendered career
    pages where ATS links aren't present in the static HTML.

    Returns UNKNOWN when discovery cannot identify a supported ATS.
    """

    log.info(
        f"  {company.name}: discovering ATS from "
        f"{company.career_page}"
    )

    try:
        snapshot = fetch_page(str(company.career_page))
    except Exception as exc:
        log.warning(
            f"  {company.name}: career page fetch failed — {exc}"
        )

        # A broken/inaccessible career page should not prevent API
        # probing from attempting recovery.
        return probe_provider(company)

    result = detect_provider(snapshot)

    if result.provider is not ProviderType.UNKNOWN:
        log.info(
            f"  {company.name}: career page detected "
            f"{result.provider.value}"
            f" (identifier={result.identifier}, "
            f"confidence={result.confidence:.0%})"
        )
        return result

    log.info(
        f"  {company.name}: career page detection found nothing — "
        "trying ATS API probe"
    )

    result = probe_provider(company)

    if result.provider is not ProviderType.UNKNOWN:
        log.info(
            f"  {company.name}: API probe detected "
            f"{result.provider.value}"
            f" (identifier={result.identifier}, "
            f"confidence={result.confidence:.0%})"
        )
    else:
        log.warning(
            f"  {company.name}: unable to discover a supported ATS"
        )

    return result