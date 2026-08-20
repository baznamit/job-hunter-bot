"""
src.main
--------
Bot entrypoint. Fetches jobs from every resolved company, filters by
keyword / location / seniority, deduplicates against the seen store,
and pushes new matches to Telegram.

Run via the Job Hunter workflow:
    python -m src.main
"""

import json
import sys
from pathlib import Path

from models import Job
from models.company import ProviderType
from research.discovery import discover_provider
from research.loader import load_registry
from research.validator import validate_candidate
from src.filters import JobFilter
from src.notifier import TelegramNotifier
from src.providers import AshbyAdapter, GreenhouseAdapter, LeverAdapter, WorkdayAdapter, SmartRecruitersAdapter, OracleAdapter, HigherAdapter, SuccessFactorsAdapter
from src.providers.exceptions import (
    ProviderNotFoundError,
    ProviderTemporaryError,
)
from src.store import SeenStore
from src.description_diagnostics import (
    enrich_near_misses,
    promotable_jobs,
)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SEEN_FILE = _PROJECT_ROOT / "data" / "seen.json"
_SETTINGS_FILE = _PROJECT_ROOT / "config" / "settings.json"

_ADAPTERS = {
    ProviderType.GREENHOUSE: GreenhouseAdapter(),
    ProviderType.LEVER: LeverAdapter(),
    ProviderType.ASHBY: AshbyAdapter(),
    ProviderType.WORKDAY: WorkdayAdapter(),
    ProviderType.SMARTRECRUITERS: SmartRecruitersAdapter(),
    ProviderType.ORACLE: OracleAdapter(),
    ProviderType.HIGHER: HigherAdapter(),
    ProviderType.SUCCESSFACTORS: SuccessFactorsAdapter(),
}

def _recover_stale_provider(company):
    """
    Attempt to recover a stale ATS mapping.

    Recovery flow:
        official career page
        -> discover ATS
        -> validate discovered configuration
        -> return temporary recovered Company

    The registry and companies.json are not modified.
    """

    print(
        f"  [RECOVERY] {company.name}: attempting ATS rediscovery...",
        file=sys.stderr,
    )

    try:
        result = discover_provider(company)
    except Exception as exc:
        print(
            f"  [RECOVERY] {company.name}: discovery failed — {exc}",
            file=sys.stderr,
        )
        return None

    if result.provider == ProviderType.UNKNOWN:
        print(
            f"  [RECOVERY] {company.name}: no supported ATS discovered",
            file=sys.stderr,
        )
        return None

    print(
        f"  [RECOVERY] {company.name}: discovered "
        f"{result.provider.value} "
        f"(confidence={result.confidence:.0%})",
        file=sys.stderr,
    )

    try:
        candidate = validate_candidate(company, result)
    except Exception as exc:
        print(
            f"  [RECOVERY] {company.name}: candidate validation "
            f"failed — {exc}",
            file=sys.stderr,
        )
        return None

    if candidate is None:
        print(
            f"  [RECOVERY] {company.name}: discovered ATS "
            "failed validation",
            file=sys.stderr,
        )
        return None

    print(
        f"  [RECOVERY] {company.name}: recovered using "
        f"{candidate.provider.type.value}",
        file=sys.stderr,
    )

    return candidate

def _max_jobs() -> int:
    settings = json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
    return settings["telegram"]["max_jobs_per_message"]


def _build_message(jobs: list[Job], limit: int) -> str:
    lines = [
        "🤖 Job Hunter",
        "",
        f"🆕 {len(jobs)} new job(s)",
        "",
    ]
    for i, job in enumerate(jobs[:limit], 1):
        lines += [
            f"{i}. {job.company}",
            f"💼 {job.title}",
            f"📍 {job.location}",
            str(job.url),
            "",
        ]
    remaining = len(jobs) - limit
    if remaining > 0:
        lines.append(f"...and {remaining} more job(s) not shown.")
    return "\n".join(lines)


def _fetch_jobs_with_recovery(
    company,
    adapter,
) -> list[Job] | None:
    """Fetch jobs, recovering automatically from a stale ATS mapping."""

    try:
        return adapter.fetch_jobs(company)

    except ProviderNotFoundError as exc:
        print(
            f"  [STALE] {company.name}: "
            f"ATS mapping appears invalid — {exc}",
            file=sys.stderr,
        )
        return _recover_and_retry_fetch(company)

    except ProviderTemporaryError as exc:
        print(
            f"  [WARN] {company.name}: "
            f"temporary ATS failure — {exc}",
            file=sys.stderr,
        )
        return None

    except Exception as exc:
        print(
            f"  [WARN] {company.name}: "
            f"fetch failed — {exc}",
            file=sys.stderr,
        )
        return None


def _recover_and_retry_fetch(company) -> list[Job] | None:
    """Attempt to recover from stale provider and retry fetching jobs."""
    recovered_company = _recover_stale_provider(company)

    if recovered_company is None:
        print(
            f"  [WARN] {company.name}: automatic ATS recovery failed",
            file=sys.stderr,
        )
        return None

    recovered_adapter = _ADAPTERS.get(recovered_company.provider.type)

    if recovered_adapter is None:
        print(
            f"  [WARN] {company.name}: recovered provider "
            f"{recovered_company.provider.type.value} "
            "has no adapter",
            file=sys.stderr,
        )
        return None

    try:
        jobs = recovered_adapter.fetch_jobs(recovered_company)
        print(
            f"  [RECOVERED] {company.name}: jobs fetched using "
            f"{recovered_company.provider.type.value}",
            file=sys.stderr,
        )
        return jobs
    except ProviderNotFoundError as exc:
        print(
            f"  [WARN] {company.name}: recovered ATS became "
            f"invalid during retry — {exc}",
            file=sys.stderr,
        )
        return None
    except ProviderTemporaryError as exc:
        print(
            f"  [WARN] {company.name}: recovered ATS had a "
            f"temporary failure — {exc}",
            file=sys.stderr,
        )
        return None
    except Exception as exc:
        print(
            f"  [WARN] {company.name}: recovered ATS fetch "
            f"failed — {exc}",
            file=sys.stderr,
        )
        return None


def _process_jobs_for_company(jobs, job_filter) -> tuple[list[Job], int, int]:
    """Filter and promote jobs, returning matching jobs and counts."""
    matching = [
        job
        for job in jobs
        if job_filter.should_include(job)
    ]

    enriched_near_misses = enrich_near_misses(
        jobs,
        job_filter,
        limit=8,
    )

    promoted = promotable_jobs(
        enriched_near_misses,
        job_filter,
    )

    direct_count = len(matching)
    matching_urls = {str(job.url) for job in matching}
    promoted_count = 0

    for job in promoted:
        if str(job.url) not in matching_urls:
            matching.append(job)
            matching_urls.add(str(job.url))
            promoted_count += 1

    return matching, direct_count, promoted_count


def _print_company_stats(company, jobs_fetched, direct_count, promoted_count, total_matching) -> None:
    """Print job processing statistics for a company."""
    if promoted_count:
        print(
            f"  {company.name}: "
            f"{jobs_fetched} fetched, "
            f"{direct_count} direct + "
            f"{promoted_count} promoted = "
            f"{total_matching} matching"
        )
    else:
        print(
            f"  {company.name}: "
            f"{jobs_fetched} fetched, "
            f"{total_matching} matching"
        )


def _send_notifications(store, notifier, new_jobs) -> None:
    """Send notification with new jobs and mark them as seen."""
    try:
        message = _build_message(new_jobs, _max_jobs())
        notifier.send_message(message)
        store.mark_seen(new_jobs)
        print(f"Telegram notification sent ({len(new_jobs)} job(s)).")
    except Exception as exc:
        # Don't mark as seen — will retry on the next run.
        print(f"[ERROR] Notification failed: {exc}", file=sys.stderr)
        sys.exit(1)


def main() -> None:

    registry = load_registry()
    job_filter = JobFilter()
    store = SeenStore(_SEEN_FILE)
    notifier = TelegramNotifier()

    all_matching: list[Job] = []

    print()
    for company in registry.companies:
        if not company.enabled:
            continue

        adapter = _ADAPTERS.get(company.provider.type)
        if adapter is None:
            continue  # Provider not implemented by this runtime.

        jobs = _fetch_jobs_with_recovery(
            company,
            adapter,
        )

        if jobs is None:
            continue

        matching, direct_count, promoted_count = _process_jobs_for_company(
            jobs, job_filter
        )

        _print_company_stats(
            company,
            len(jobs),
            direct_count,
            promoted_count,
            len(matching),
        )

        all_matching.extend(matching)

    new_jobs = store.filter_new(all_matching)

    print()
    print(f"  Matching : {len(all_matching)}")
    print(f"  New      : {len(new_jobs)}")
    print()

    if not new_jobs:
        print("No new jobs to notify.")
        return

    _send_notifications(store, notifier, new_jobs)
        
if __name__ == "__main__":
    main()
