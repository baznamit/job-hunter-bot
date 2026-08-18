import html
import re
from dataclasses import dataclass

import requests

from models import Job
from src.filters import JobFilter, RejectionReason


_TIMEOUT = 15
_MAX_DESCRIPTION_CHARS = 200_000

_POSITIVE_SIGNALS = (
    "java",
    "spring",
    "spring boot",
    "backend",
    "back-end",
    "microservices",
    "microservice",
    "rest api",
    "restful",
    "api development",
    "kafka",
    "distributed systems",
    "server-side",
    "server side",
    "jvm",
    "hibernate",
    "jpa",
    "sql",
    "aws",
    "azure",
    "gcp",
    "kubernetes",
    "docker",
)

_STRONG_SIGNALS = (
    "java",
    "spring",
    "spring boot",
    "backend",
    "back-end",
    "microservices",
    "microservice",
    "kafka",
    "distributed systems",
    "server-side",
    "server side",
    "jvm",
)

# These are useful for eliminating obviously irrelevant engineering
# roles before making an extra HTTP request.
_TITLE_REJECT_TERMS = (
    "engineering manager",
    "manager, engineering",
    "manager software engineering",
    "manager, software engineering",
    "vice president",
    "director",
    "data engineer",
    "data scientist",
    "machine learning",
    "ml engineer",
    "ai engineer",
    "site reliability",
    "sre",
    "security engineer",
    "network engineer",
    "datacenter",
    "data center",
    "firmware",
    "qa engineer",
    "test engineer",
    "sdet",
    "support engineer",
    "solutions engineer",
    "solution engineer",
)

_TARGET_CITIES = (
    "mumbai",
    "bangalore",
    "bengaluru",
)


@dataclass
class EnrichedNearMiss:
    job: Job
    rejection_reason: RejectionReason
    signals: list[str]
    strong: bool


def _strip_html(raw: str) -> str:
    """
    Convert a fetched HTML job page into searchable plain-ish text.

    This is deliberately lightweight: diagnostics only need technology
    signals, not a perfect representation of the page.
    """

    raw = raw[:_MAX_DESCRIPTION_CHARS]

    raw = re.sub(
        r"<script\b[^>]*>.*?</script>",
        " ",
        raw,
        flags=re.IGNORECASE | re.DOTALL,
    )
    raw = re.sub(
        r"<style\b[^>]*>.*?</style>",
        " ",
        raw,
        flags=re.IGNORECASE | re.DOTALL,
    )
    raw = re.sub(r"<[^>]+>", " ", raw)

    raw = html.unescape(raw)

    return re.sub(r"\s+", " ", raw).strip().lower()


def _location_is_diagnostic_target(job: Job) -> bool:
    location = job.location.lower()

    if any(city in location for city in _TARGET_CITIES):
        return True

    if location == "india":
        return True

    if "remote" in location and (
        "india" in location
        or location.strip() == "remote"
    ):
        return True

    return False


def should_enrich(
    job: Job,
    reason: RejectionReason,
    job_filter: JobFilter,
) -> bool:
    """
    Return True only for useful diagnostic candidates.

    This intentionally uses stricter rules than the general near-miss
    logger so we don't fetch hundreds of job-description pages.
    """

    title = job.title.lower()

    if any(term in title for term in _TITLE_REJECT_TERMS):
        return False

    if not _location_is_diagnostic_target(job):
        return False

    if reason == RejectionReason.INCLUDE_KEYWORD:
        return (
            "engineer" in title
            or "developer" in title
            or "computer scientist" in title
            or "technical staff" in title
        )

    if reason == RejectionReason.SENIORITY:
        # Senior software engineer/developer is explicitly interesting
        # for diagnostics. Lead/staff/principal/etc. are not promoted
        # here merely because they are senior.
        return (
            "senior software engineer" in title
            or "senior software developer" in title
        )

    if reason == RejectionReason.LOCATION:
        # Only broad India / Remote India jobs should be enriched.
        return (
            job_filter._include_keyword_match(job.title)
            and _location_is_diagnostic_target(job)
        )

    # Excluded-keyword candidates are intentionally not description-
    # enriched yet. This avoids spending requests on internships,
    # mobile, QA, staff/principal, etc.
    return False


def fetch_description_text(job: Job) -> str | None:
    try:
        response = requests.get(
            str(job.url),
            timeout=_TIMEOUT,
            allow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (compatible; JobHunterBot/1.0)"
                ),
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        response.raise_for_status()
    except requests.RequestException:
        return None

    return _strip_html(response.text)


def find_signals(text: str) -> list[str]:
    """
    Find relevant backend/platform technology signals.

    Matching is case-insensitive and avoids reporting shorter signals
    when a more specific equivalent signal is already present.
    """

    text = text.lower()

    found: list[str] = []

    for signal in _POSITIVE_SIGNALS:
        if signal in text:
            found.append(signal)

    # Avoid duplicate-equivalent signals.
    if "spring boot" in found and "spring" in found:
        found.remove("spring")

    if "microservices" in found and "microservice" in found:
        found.remove("microservice")

    if "back-end" in found and "backend" in found:
        found.remove("back-end")

    if "server-side" in found and "server side" in found:
        found.remove("server side")

    return found


def enrich_near_misses(
    jobs: list[Job],
    job_filter: JobFilter,
    limit: int = 20,
) -> list[EnrichedNearMiss]:
    """
    Fetch descriptions for at most `limit` promising rejected jobs.

    Production filtering is not modified.
    """

    candidates: list[tuple[Job, RejectionReason]] = []

    for job in jobs:
        result = job_filter.evaluate(job)

        if result.included or result.reason is None:
            continue

        if should_enrich(
            job,
            result.reason,
            job_filter,
        ):
            candidates.append(
                (job, result.reason)
            )

        if len(candidates) >= limit:
            break

    enriched: list[EnrichedNearMiss] = []

    for job, reason in candidates:
        text = fetch_description_text(job)

        if not text:
            continue

        signals = find_signals(text)

        if not signals:
            continue

        strong_count = sum(
            1
            for signal in signals
            if signal in _STRONG_SIGNALS
        )

        enriched.append(
            EnrichedNearMiss(
                job=job,
                rejection_reason=reason,
                signals=signals,
                strong=strong_count >= 2,
            )
        )

    return enriched