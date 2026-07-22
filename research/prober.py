"""
research.prober
---------------
Fallback detection strategy for companies whose career pages are JavaScript-
rendered SPAs. Instead of scraping HTML (which is empty before JS runs), we
directly probe the public ATS APIs using slug candidates derived from the
company registry entry.

This is deliberately kept separate from the page-based detectors because it
makes live network calls and is used only when HTML detection produces UNKNOWN.
"""

import requests

from models import DetectionResult
from models.company import Company, ProviderType
from research.logger import get_logger

log = get_logger(__name__)

_TIMEOUT = 10


def _slug_candidates(company: Company) -> list[str]:
    """
    Generate ordered slug candidates from company metadata.
    Most ATS slugs match the company id directly; the name variants are
    low-cost fallbacks.
    """
    name = company.name.lower()
    seen: set[str] = set()
    candidates: list[str] = []

    for raw in [company.id, name.replace(" ", ""), name.replace(" ", "-")]:
        if raw not in seen:
            seen.add(raw)
            candidates.append(raw)

    return candidates


def _probe_greenhouse(slug: str) -> bool:
    try:
        r = requests.get(
            f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
            timeout=_TIMEOUT,
        )
        return r.status_code == 200
    except Exception:
        return False


def _probe_lever(slug: str) -> bool:
    try:
        r = requests.get(
            f"https://api.lever.co/v0/postings/{slug}",
            timeout=_TIMEOUT,
        )
        return r.status_code == 200
    except Exception:
        return False


def _probe_ashby(slug: str) -> bool:
    try:
        r = requests.get(
            f"https://api.ashbyhq.com/posting-api/job-board/{slug}",
            timeout=_TIMEOUT,
        )
        return r.status_code == 200
    except Exception:
        return False


# Ordered by prevalence among tech companies.
_PROBERS: list[tuple[ProviderType, object]] = [
    (ProviderType.GREENHOUSE, _probe_greenhouse),
    (ProviderType.LEVER, _probe_lever),
    (ProviderType.ASHBY, _probe_ashby),
]


def probe_provider(company: Company) -> DetectionResult:
    """
    Probe each ATS API with slug candidates derived from the company's id/name.
    Returns the first successful match, or UNKNOWN if none respond.
    """
    candidates = _slug_candidates(company)
    log.info(f"  {company.name}: probing API with candidates {candidates}")

    for slug in candidates:
        for provider_type, probe_fn in _PROBERS:
            if probe_fn(slug):
                return DetectionResult(
                    provider=provider_type,
                    confidence=0.85,
                    reason=f"ATS API responded 200 for slug '{slug}'.",
                    identifier=slug,
                )

    return DetectionResult(
        provider=ProviderType.UNKNOWN,
        confidence=0.0,
        reason="No ATS API responded for any slug candidate.",
    )
