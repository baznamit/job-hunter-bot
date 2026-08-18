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

def _candidate_score(
    job: Job,
    reason: RejectionReason,
) -> int:
    """
    Rank diagnostic candidates before description fetching.

    Higher scores represent jobs that are more likely to be useful
    backend/software-engineering near misses.
    """

    title = job.title.lower()
    location = job.location.lower()

    score = 0

    # Prefer exact target cities over broad India/remote locations.
    if any(city in location for city in _TARGET_CITIES):
        score += 40
    elif "remote" in location and "india" in location:
        score += 25
    elif location.strip() == "remote":
        score += 15
    elif location == "india" or location.endswith(", india"):
        score += 10

    # Strong software-development role families.
    if "software development engineer" in title:
        score += 100
    elif "software engineer" in title:
        score += 95
    elif "software developer" in title:
        score += 95
    elif "backend engineer" in title:
        score += 95
    elif "backend developer" in title:
        score += 95
    elif "computer scientist" in title:
        score += 90
    elif "platform engineer" in title:
        score += 85
    elif "application engineer" in title:
        score += 80
    elif "application developer" in title:
        score += 80
    elif "member of technical staff" in title:
        score += 80
    elif "technical staff" in title:
        score += 75
    elif "forward deployed engineer" in title:
        score += 70
    elif "engineer" in title:
        score += 50
    elif "developer" in title:
        score += 50

    # Backend/platform hints already present in the title.
    for term in (
        "java",
        "backend",
        "platform",
        "kafka",
        "messaging",
        "distributed",
        "api",
        "infrastructure",
    ):
        if term in title:
            score += 15

    # Senior SWE/SWD is explicitly acceptable for diagnostics.
    if (
        "senior software engineer" in title
        or "senior software developer" in title
    ):
        score += 20

    # Jobs rejected only because their title vocabulary is too narrow
    # are especially useful for description analysis.
    if reason == RejectionReason.INCLUDE_KEYWORD:
        score += 20

    return score

def enrich_near_misses(
    jobs: list[Job],
    job_filter: JobFilter,
    limit: int = 20,
) -> list[EnrichedNearMiss]:
    """
    Fetch descriptions for at most `limit` promising rejected jobs.

    Production filtering is not modified.
    """

    ranked_candidates: list[
        tuple[int, int, Job, RejectionReason]
    ] = []

    for index, job in enumerate(jobs):
        result = job_filter.evaluate(job)

        if result.included or result.reason is None:
            continue

        if not should_enrich(
            job,
            result.reason,
            job_filter,
        ):
            continue

        score = _candidate_score(
            job,
            result.reason,
        )

        ranked_candidates.append(
            (
                score,
                index,
                job,
                result.reason,
            )
        )

    ranked_candidates.sort(
        key=lambda item: (
            -item[0],
            item[1],
        )
    )

    candidates = [
        (job, reason)
        for _, _, job, reason
        in ranked_candidates[:limit]
    ]

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

def promotable_jobs(
    near_misses: list[EnrichedNearMiss],
    job_filter: JobFilter,
) -> list[Job]:
    """
    Return description-verified near misses that are safe to promote
    into the production matching set.

    Promotion is deliberately conservative:
    - description must have >= 2 strong backend signals
    - location must satisfy the production location rule
    - title must pass production exclusion rules
    - title must pass production seniority rules
    - original failure must be the narrow include-keyword rule

    This prevents description enrichment from bypassing hard filters.
    """

    promoted: list[Job] = []

    for item in near_misses:
        job = item.job

        if not item.strong:
            continue

        if item.rejection_reason != RejectionReason.INCLUDE_KEYWORD:
            continue

        if not job_filter._exclude_keyword_match(job.title):
            continue

        if not job_filter._location_match(job.location):
            continue

        if not job_filter._seniority_match(job.title):
            continue

        promoted.append(job)

    return promoted