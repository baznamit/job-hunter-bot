"""
research.mapper
---------------
Fetches each company's career page, detects the ATS in use, and writes the
resolved provider type + config back into config/companies.json.

Only companies that are both enabled AND still in research_pending status are
processed, so manually-verified entries are never overwritten.

Run via the map.yml workflow:
    python -m research.mapper
"""

import json

from models.company import ProviderStatus, ProviderType
from research.loader import load_registry
from research.logger import get_logger
from research.paths import COMPANIES_FILE
from research.discovery import discover_provider

log = get_logger(__name__)


def _apply_config(
    raw_provider: dict,
    provider_type: ProviderType,
    identifier: str | None,
    config: dict[str, str],
    ) -> None:
    """
    Apply discovered provider configuration to the registry.

    Structured config takes priority. The legacy identifier is retained
    as a fallback for Greenhouse, Lever, and Ashby detectors.
    """

    if config:
        raw_provider["config"] = dict(config)
        return

    if identifier is None:
        return

    if provider_type in (
        ProviderType.GREENHOUSE,
        ProviderType.LEVER,
    ):
        raw_provider["config"] = {
            "board": identifier,
        }

    elif provider_type is ProviderType.ASHBY:
        raw_provider["config"] = {
            "organization": identifier,
        }


def run() -> int:
    """
    Map unknown companies. Returns the count of newly mapped companies.
    """
    with COMPANIES_FILE.open("r", encoding="utf-8") as fh:
        raw = json.load(fh)

    registry = load_registry()

    mapped = 0
    unchanged = 0

    for i, company in enumerate(registry.companies):
        if not company.enabled:
            log.info(f"  {company.name}: skipped (disabled)")
            continue

        if company.provider.status == ProviderStatus.VERIFIED:
            log.info(
                f"  {company.name}: skipped "
                f"(status={company.provider.status.value})"
            )
            unchanged += 1
            continue

        log.info(f"  {company.name}: fetching {company.career_page} ...")

        try:
            result = discover_provider(company)
        except Exception as exc:
            log.warning(f"  {company.name}: discovery failed — {exc}")
            continue

        if result.provider is ProviderType.UNKNOWN:
            log.warning(
                f"  {company.name}: no ATS signature found — "
                "mark provider manually or add a new detector"
            )
            continue

        log.info(
            f"  {company.name}: detected {result.provider.value}"
            f" (slug={result.identifier}, confidence={result.confidence:.0%})"
        )

        raw_provider = raw["companies"][i]["provider"]
        raw_provider["type"] = result.provider.value
        raw_provider["status"] = ProviderStatus.PARTIAL.value

        _apply_config(raw_provider,result.provider,result.identifier,result.config,)

        mapped += 1

    with COMPANIES_FILE.open("w", encoding="utf-8") as fh:
        json.dump(raw, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    log.info(f"\nDone: {mapped} mapped, {unchanged} already resolved.")
    return mapped


if __name__ == "__main__":
    run()
