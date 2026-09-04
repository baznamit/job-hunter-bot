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
import time
from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed,
)
from pathlib import Path

from models import Job
from models.company import ProviderType
from research.discovery import discover_provider
from research.loader import load_registry
from research.validator import validate_candidate
from src.description_diagnostics import (
    enrich_near_misses,
    promotable_jobs,
)
from src.filters import JobFilter
from src.notifier import TelegramNotifier
from src.providers import AshbyAdapter, GreenhouseAdapter, LeverAdapter, WorkdayAdapter, SmartRecruitersAdapter, OracleAdapter, HigherAdapter, SuccessFactorsAdapter, TalentBrewAdapter, AlgoliaAdapter, BankOfAmericaAdapter
from src.providers.exceptions import (
    ProviderNotFoundError,
    ProviderTemporaryError,
)
from src.recovery_store import RecoveryStore
from src.run_result import CompanyRunResult
from src.store import SeenStore

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SEEN_FILE = _PROJECT_ROOT / "data" / "seen.json"
_RECOVERY_FILE = (
    _PROJECT_ROOT
    / "data"
    / "recovery.json"
)
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
    ProviderType.TALENTBREW: TalentBrewAdapter(),
    ProviderType.ALGOLIA: AlgoliaAdapter(),
    ProviderType.BANKOFAMERICA: BankOfAmericaAdapter(),
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


def _settings() -> dict:
    return json.loads(
        _SETTINGS_FILE.read_text(
            encoding="utf-8"
        )
    )


def _max_jobs(
    settings: dict,
) -> int:
    return settings[
        "telegram"
    ][
        "max_jobs_per_message"
    ]


def _max_workers(
    settings: dict,
) -> int:
    return int(
        settings.get(
            "runtime",
            {},
        ).get(
            "max_workers",
            6,
        )
    )


def _performance_top_n(
    settings: dict,
) -> int:
    return int(
        settings.get(
            "runtime",
            {},
        ).get(
            "performance_top_n",
            10,
        )
    )


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
    recovery_store: RecoveryStore,
    recovery_settings: dict,
) -> list[Job] | None:
    """
    Fetch jobs and recover stale ATS mappings.

    Repeated failed rediscovery attempts are subject
    to exponential cooldown.
    """

    try:
        jobs = adapter.fetch_jobs(
            company
        )

        recovery_store.clear(
            company.id
        )

        return jobs

    except ProviderNotFoundError as exc:
        print(
            f"  [STALE] {company.name}: "
            f"ATS mapping appears invalid — {exc}",
            file=sys.stderr,
        )

        should_attempt, retry_at = (
            recovery_store.should_attempt(
                company.id
            )
        )

        if not should_attempt:
            print(
                f"  [RECOVERY] {company.name}: "
                f"skipped — retry after "
                f"{retry_at.isoformat()}",
                file=sys.stderr,
            )

            return None

        jobs = _recover_and_retry_fetch(
            company
        )

        if jobs is None:
            recovery_store.record_failure(
                company.id,
                base_hours=int(
                    recovery_settings.get(
                        "base_cooldown_hours",
                        6,
                    )
                ),
                max_hours=int(
                    recovery_settings.get(
                        "max_cooldown_hours",
                        72,
                    )
                ),
            )

            return None

        recovery_store.clear(
            company.id
        )

        return jobs

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


def _send_notifications(
    store,
    notifier,
    new_jobs,
    max_jobs: int,
) -> None:
    """Send notification with new jobs and mark them as seen."""
    try:
        message = _build_message(
            new_jobs,
            max_jobs,
        )
        notifier.send_message(message)
        store.mark_seen(new_jobs)
        print(f"Telegram notification sent ({len(new_jobs)} job(s)).")
    except Exception as exc:
        # Don't mark as seen — will retry on the next run.
        print(f"[ERROR] Notification failed: {exc}", file=sys.stderr)
        sys.exit(1)


def _run_company(
    company,
    adapter,
    job_filter: JobFilter,
    recovery_store: RecoveryStore,
    recovery_settings: dict,
) -> CompanyRunResult:
    started = time.perf_counter()

    result = CompanyRunResult(
        company_id=company.id,
        company_name=company.name,
        provider=(
            company.provider.type.value
        ),
    )

    try:
        jobs = _fetch_jobs_with_recovery(
            company,
            adapter,
            recovery_store,
            recovery_settings,
        )

        if jobs is None:
            result.success = False
            return result

        result.jobs_fetched = len(
            jobs
        )

        (
            matching,
            direct_count,
            promoted_count,
        ) = _process_jobs_for_company(
            jobs,
            job_filter,
        )

        result.matching = matching
        result.direct_count = (
            direct_count
        )
        result.promoted_count = (
            promoted_count
        )

        return result

    except Exception as exc:
        result.success = False
        result.error = (
            f"{type(exc).__name__}: {exc}"
        )

        print(
            f"  [WARN] {company.name}: "
            f"worker failed — {exc}",
            file=sys.stderr,
        )

        return result

    finally:
        result.elapsed_seconds = (
            time.perf_counter()
            - started
        )


def _print_performance_summary(
    results: list[CompanyRunResult],
    total_seconds: float,
    top_n: int,
) -> None:
    completed = [
        result
        for result in results
        if result.success
    ]

    failed = [
        result
        for result in results
        if not result.success
    ]

    jobs_fetched = sum(
        result.jobs_fetched
        for result in completed
    )

    matching = sum(
        len(result.matching)
        for result in completed
    )

    slowest = sorted(
        results,
        key=lambda item: (
            item.elapsed_seconds
        ),
        reverse=True,
    )[:top_n]

    print()
    print("Performance")
    print("-----------")

    print(
        f"Companies processed : "
        f"{len(results)}"
    )

    print(
        f"Successful          : "
        f"{len(completed)}"
    )

    print(
        f"Failed/skipped      : "
        f"{len(failed)}"
    )

    print(
        f"Jobs fetched        : "
        f"{jobs_fetched}"
    )

    print(
        f"Matching            : "
        f"{matching}"
    )

    print(
        f"Total runtime       : "
        f"{total_seconds:.1f}s"
    )

    print()
    print("Slowest companies:")

    for index, result in enumerate(
        slowest,
        1,
    ):
        status = (
            "ok"
            if result.success
            else "failed"
        )

        print(
            f"{index:>2}. "
            f"{result.company_name:<28} "
            f"{result.elapsed_seconds:>7.1f}s "
            f"{result.jobs_fetched:>6} jobs "
            f"[{result.provider}, {status}]"
        )


def main() -> None:
    run_started = time.perf_counter()

    settings = _settings()

    registry = load_registry()

    job_filter = JobFilter()

    store = SeenStore(
        _SEEN_FILE
    )

    recovery_store = RecoveryStore(
        _RECOVERY_FILE
    )

    notifier = TelegramNotifier()

    recovery_settings = settings.get(
        "recovery",
        {},
    )

    max_workers = _max_workers(
        settings
    )

    companies = []

    for company in registry.companies:
        if not company.enabled:
            continue

        adapter = _ADAPTERS.get(
            company.provider.type
        )

        if adapter is None:
            continue

        companies.append(
            (
                company,
                adapter,
            )
        )

    print()
    print(
        f"Processing "
        f"{len(companies)} companies "
        f"with {max_workers} workers..."
    )
    print()

    results: list[
        CompanyRunResult
    ] = []

    with ThreadPoolExecutor(
        max_workers=max_workers
    ) as executor:

        future_map = {
            executor.submit(
                _run_company,
                company,
                adapter,
                job_filter,
                recovery_store,
                recovery_settings,
            ): company
            for company, adapter
            in companies
        }

        for future in as_completed(
            future_map
        ):
            company = future_map[
                future
            ]

            try:
                result = future.result()

            except Exception as exc:
                print(
                    f"  [WARN] "
                    f"{company.name}: "
                    f"unexpected worker "
                    f"failure — {exc}",
                    file=sys.stderr,
                )

                continue

            results.append(
                result
            )

            if not result.success:
                continue

            _print_company_stats(
                company,
                result.jobs_fetched,
                result.direct_count,
                result.promoted_count,
                len(result.matching),
            )

            print(
                f"    [TIME] "
                f"{result.elapsed_seconds:.1f}s "
                f"via {result.provider}"
            )

    order = {
        company.id: index
        for index, (
            company,
            _,
        ) in enumerate(companies)
    }

    results.sort(
        key=lambda result: order.get(
            result.company_id,
            10**9,
        )
    )

    all_matching = [
        job
        for result in results
        if result.success
        for job in result.matching
    ]

    new_jobs = store.filter_new(
        all_matching
    )

    total_seconds = (
        time.perf_counter()
        - run_started
    )

    print()
    print(
        f"  Matching : "
        f"{len(all_matching)}"
    )
    print(
        f"  New      : "
        f"{len(new_jobs)}"
    )

    _print_performance_summary(
        results,
        total_seconds,
        _performance_top_n(
            settings
        ),
    )

    print()

    if not new_jobs:
        print(
            "No new jobs to notify."
        )
        return

    _send_notifications(
        store,
        notifier,
        new_jobs,
        _max_jobs(settings),
    )


if __name__ == "__main__":
    main()
