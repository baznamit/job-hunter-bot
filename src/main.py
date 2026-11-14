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
from dataclasses import dataclass
from datetime import (
    datetime,
    timezone,
)
from types import SimpleNamespace
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
from src.notifier import (
    MAX_MESSAGE_LEN,
    TelegramNotifier,
    message_length,
)
from src.providers import (
    AlgoliaAdapter,
    AtlassianAdapter,
    AshbyAdapter,
    BankOfAmericaAdapter,
    CognizantAdapter,
    EightfoldAdapter,
    FyndAdapter,
    GreenhouseAdapter,
    HCLTechAdapter,
    HigherAdapter,
    IBMAdapter,
    InfosysAdapter,
    KekaAdapter,
    KulaAdapter,
    LeverAdapter,
    OracleAdapter,
    PhonePeAdapter,
    SmartRecruitersAdapter,
    SuccessFactorsAdapter,
    TalentBrewAdapter,
    WorkdayAdapter,
    ZohoRecruitAdapter,
)
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
    ProviderType.ATLASSIAN: AtlassianAdapter(),
    ProviderType.SMARTRECRUITERS: SmartRecruitersAdapter(),
    ProviderType.ORACLE: OracleAdapter(),
    ProviderType.HIGHER: HigherAdapter(),
    ProviderType.SUCCESSFACTORS: SuccessFactorsAdapter(),
    ProviderType.TALENTBREW: TalentBrewAdapter(),
    ProviderType.ALGOLIA: AlgoliaAdapter(),
    ProviderType.BANKOFAMERICA: BankOfAmericaAdapter(),
    ProviderType.PHONEPE: PhonePeAdapter(),
    ProviderType.KEKA: KekaAdapter(),
    ProviderType.KULA: KulaAdapter(),
    ProviderType.EIGHTFOLD: EightfoldAdapter(),
    ProviderType.COGNIZANT: CognizantAdapter(),
    ProviderType.ZOHO_RECRUIT: ZohoRecruitAdapter(),
    ProviderType.FYND: FyndAdapter(),
    ProviderType.INFOSYS: InfosysAdapter(),
    ProviderType.HCLTECH: HCLTechAdapter(),
    ProviderType.IBM: IBMAdapter(),
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
    value = settings[
        "telegram"
    ][
        "max_jobs_per_message"
    ]
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(
            "telegram.max_jobs_per_message must be a positive integer"
        )
    return value


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


def _notification_location_rank(
    job: Job,
    settings: dict,
) -> int:
    """
    Rank an already-eligible job for presentation.

    Lower number = higher notification priority.

    Eligibility remains JobFilter's responsibility.
    This function affects ordering only.
    """

    location = (
        job.location
        or ""
    ).lower()

    groups = (
        settings.get(
            "locations",
            {},
        ).get(
            "notification_priority",
            [],
        )
    )

    for rank, group in enumerate(
        groups
    ):
        terms = group.get(
            "terms",
            []
        )

        if any(
            str(term).lower()
            in location
            for term in terms
        ):
            return rank

    # Explicit India listings come after
    # configured preferred-city groups.
    if "india" in location:
        return len(groups)

    # Generic remote comes last.
    if "remote" in location:
        return len(groups) + 1

    # Defensive fallback. Normally such a job
    # should already have been rejected by JobFilter.
    return len(groups) + 2


def _posted_timestamp(
    job: Job,
) -> float:
    posted_at = job.posted_at

    if posted_at is None:
        return 0.0

    if posted_at.tzinfo is None:
        posted_at = posted_at.replace(
            tzinfo=timezone.utc
        )

    return posted_at.timestamp()


def _sort_notification_jobs(
    jobs: list[Job],
    settings: dict,
) -> list[Job]:
    """
    Presentation ordering:

    1. configured location priority
    2. newest posting first
    3. deterministic company/title fallback
    """

    return sorted(
        jobs,
        key=lambda job: (
            _notification_location_rank(
                job,
                settings,
            ),
            -_posted_timestamp(job),
            job.company.lower(),
            job.title.lower(),
        ),
    )


def _notification_location_group(
    job: Job,
    settings: dict,
) -> str:
    location = (
        job.location
        or ""
    ).lower()

    groups = (
        settings.get(
            "locations",
            {},
        ).get(
            "notification_priority",
            [],
        )
    )

    for group in groups:
        if any(
            str(term).lower()
            in location
            for term in group.get(
                "terms",
                []
            )
        ):
            return str(
                group.get(
                    "name",
                    "Preferred",
                )
            )

    if "remote" in location:
        return "India / Remote"

    return "Other India"


@dataclass(frozen=True)
class NotificationBatch:
    jobs: list[Job]
    message: str


def _compact_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: max(1, limit - 1)] + "…"


def _job_lines(job: Job, *, compact: bool = False) -> list[str]:
    company = str(job.company)
    title = str(job.title)
    location = str(job.location)

    if compact:
        company = _compact_text(company, 120)
        title = _compact_text(title, 180)
        location = _compact_text(location, 120)

    return [
        f"{company}",
        f"💼 {title}",
        f"📍 {location}",
        str(job.url),
        "",
    ]


def _render_message(
    jobs: list[Job],
    batch_number: int,
    start_number: int,
    settings: dict,
    *,
    compact: bool = False,
) -> str:
    lines = [
        "🤖 Job Hunter",
        f"📦 Batch {batch_number}",
        "",
        f"🆕 {len(jobs)} new job(s)",
        "",
    ]

    current_group = None

    for index, job in enumerate(jobs, start_number):
        group = (
            _notification_location_group(
                job,
                settings,
            )
        )

        if group != current_group:
            if current_group is not None:
                lines.append("")

            lines += [
                f"📌 {group}",
                "",
            ]

            current_group = group

        job_record = _job_lines(job, compact=compact)
        job_record[0] = f"{index}. {job_record[0]}"
        lines += job_record

    return "\n".join(lines)


def _build_message_batches(
    jobs: list[Job],
    limit: int,
    settings: dict,
) -> list[NotificationBatch]:
    """Build a complete, length-safe plan before any delivery starts."""
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        raise ValueError(
            "telegram.max_jobs_per_message must be a positive integer"
        )

    if not jobs:
        return []

    batches: list[NotificationBatch] = []
    current: list[Job] = []

    def append_current() -> None:
        if not current:
            return
        batch_number = len(batches) + 1
        start_number = sum(len(batch.jobs) for batch in batches) + 1
        message = _render_message(
            current,
            batch_number,
            start_number,
            settings,
        )
        if message_length(message) > MAX_MESSAGE_LEN:
            raise ValueError(
                f"Notification batch {batch_number} exceeds "
                f"{MAX_MESSAGE_LEN} measured characters"
            )
        batches.append(NotificationBatch(list(current), message))
        current.clear()

    for job in jobs:
        if len(current) >= limit:
            append_current()

        candidate = current + [job]
        batch_number = len(batches) + 1
        start_number = sum(len(batch.jobs) for batch in batches) + 1
        candidate_message = _render_message(
            candidate,
            batch_number,
            start_number,
            settings,
        )

        if current and message_length(candidate_message) > MAX_MESSAGE_LEN:
            append_current()
            candidate = [job]
            batch_number = len(batches) + 1
            start_number = sum(len(batch.jobs) for batch in batches) + 1
            candidate_message = _render_message(
                candidate,
                batch_number,
                start_number,
                settings,
            )

        if message_length(candidate_message) > MAX_MESSAGE_LEN:
            candidate_message = _render_message(
                [job],
                batch_number,
                start_number,
                settings,
                compact=True,
            )
            if message_length(candidate_message) > MAX_MESSAGE_LEN:
                raise ValueError(
                    "A single job notification cannot fit within "
                    f"{MAX_MESSAGE_LEN} measured characters while preserving "
                    "its complete URL"
                )
            append_current()
            batches.append(NotificationBatch([job], candidate_message))
            continue

        current.append(job)

    append_current()
    return batches


def _build_message(
    jobs: list[Job],
    limit: int,
    settings: dict,
) -> str:
    """Compatibility wrapper for callers that require one message."""
    batches = _build_message_batches(jobs, limit, settings)
    if len(batches) != 1:
        raise ValueError(
            "Jobs require multiple notification batches; use "
            "_build_message_batches()"
        )
    return batches[0].message


def _fetch_jobs_with_recovery(
    company,
    adapter,
    recovery_store: RecoveryStore,
    recovery_settings: dict,
    *,
    include_report: bool = False,
):
    """
    Fetch jobs and recover stale ATS mappings.

    A company already recorded in the recovery store is known to have
    a stale provider mapping. While its recovery cooldown is active,
    skip the known-dead provider entirely.

    Once the cooldown expires, retry the configured provider first.
    If it is still stale, attempt rediscovery.
    """

    def result(jobs, report=None):
        if include_report:
            return jobs, report
        return jobs

    should_attempt, retry_at = (
        recovery_store.should_attempt(
            company.id
        )
    )

    if not should_attempt:
        print(
            f"  [STALE-COOLDOWN] "
            f"{company.name}: skipping known-stale "
            f"{company.provider.type.value} mapping — "
            f"retry after {retry_at.isoformat()}",
            file=sys.stderr,
        )

        return result(
            None,
            SimpleNamespace(
                coverage_status="skipped",
                listing_status="skipped",
                error="expected cooldown skip",
            ),
        )

    try:
        if (
            company.provider.type == ProviderType.WORKDAY
            and callable(getattr(adapter, "fetch_jobs_with_report", None))
        ):
            jobs, report = adapter.fetch_jobs_with_report(company)
        else:
            jobs = adapter.fetch_jobs(company)
            report = SimpleNamespace(
                coverage_status="complete",
                listing_status="complete",
            )

        # The configured provider works again.
        recovery_store.clear(
            company.id
        )

        return result(jobs, report)

    except ProviderNotFoundError as exc:
        print(
            f"  [STALE] {company.name}: "
            f"ATS mapping appears invalid — {exc}",
            file=sys.stderr,
        )

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

            return result(
                None,
                SimpleNamespace(
                    coverage_status="failed",
                    listing_status="failed",
                    error="stale provider recovery failed",
                ),
            )

        recovery_store.clear(
            company.id
        )

        return result(
            jobs,
            SimpleNamespace(
                coverage_status="complete",
                listing_status="complete",
            ),
        )

    except ProviderTemporaryError as exc:
        print(
            f"  [WARN] {company.name}: "
            f"temporary ATS failure — {exc}",
            file=sys.stderr,
        )

        report = getattr(exc, "workday_report", None)
        if report is None:
            report = SimpleNamespace(
                coverage_status="failed",
                listing_status="failed",
            )
        report.error = str(exc)
        return result(None, report)

    except Exception as exc:
        print(
            f"  [WARN] {company.name}: "
            f"fetch failed — {exc}",
            file=sys.stderr,
        )

        return result(
            None,
            SimpleNamespace(
                coverage_status="failed",
                listing_status="failed",
                error=str(exc),
            ),
        )


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


def _apply_coverage_report(result: CompanyRunResult, report) -> None:
    if report is None:
        return

    for name in (
        "coverage_status",
        "listing_status",
        "enrichment_candidates",
        "enrichment_attempted",
        "enrichment_resolved",
        "enrichment_unresolved",
        "enrichment_unstarted",
        "http_attempts",
        "http_retries",
        "failure_reasons",
        "coverage_note",
    ):
        if hasattr(report, name):
            setattr(result, name, getattr(report, name))

    if hasattr(report, "deferred") and report.deferred:
        result.coverage_note = (
            f"deferred={report.deferred} stop_reason={report.stop_reason}"
        )


def _send_notifications(
    store,
    notifier,
    new_jobs,
    max_jobs: int,
    settings: dict,
) -> None:
    """Send and persist one complete notification batch at a time."""
    try:
        ordered_jobs = (
            _sort_notification_jobs(
                new_jobs,
                settings,
            )
        )
        batches = _build_message_batches(
            ordered_jobs,
            max_jobs,
            settings,
        )
        print(
            f"Notification plan: {len(ordered_jobs)} unique new job(s), "
            f"{len(batches)} batch(es)."
        )

        for index, batch in enumerate(batches, 1):
            pending = len(ordered_jobs) - sum(
                len(previous.jobs)
                for previous in batches[:index - 1]
            )
            try:
                notifier.send_message(batch.message)
            except Exception as exc:
                print(
                    f"[ERROR] Delivery failed at batch {index}/{len(batches)} "
                    f"({len(batch.jobs)} job(s)); {pending} job(s) remain "
                    f"pending: {exc}",
                    file=sys.stderr,
                )
                sys.exit(1)

            try:
                store.mark_seen(batch.jobs)
            except Exception as exc:
                print(
                    f"[ERROR] State persistence failed after acknowledged "
                    f"batch {index}/{len(batches)}; {pending} job(s) remain "
                    "pending. Telegram may have accepted this batch; a "
                    f"retry can duplicate it: {exc}",
                    file=sys.stderr,
                )
                sys.exit(1)

            print(
                f"Telegram batch {index}/{len(batches)} acknowledged and "
                f"recorded ({len(batch.jobs)} job(s))."
            )
    except Exception as exc:
        print(
            f"[ERROR] Notification plan failed before delivery: {exc}",
            file=sys.stderr,
        )
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
        jobs, report = _fetch_jobs_with_recovery(
            company,
            adapter,
            recovery_store,
            recovery_settings,
            include_report=True,
        )
        _apply_coverage_report(result, report)

        if jobs is None:
            result.success = False
            result.skipped = result.coverage_status == "skipped"
            result.error = getattr(report, "error", None)
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

    partial = [
        result for result in completed
        if result.coverage_status == "partial"
    ]
    failed_coverage = [
        result for result in results
        if result.coverage_status == "failed"
    ]
    skipped = [
        result for result in results
        if result.coverage_status == "skipped"
    ]

    print(f"Complete            : {len(completed) - len(partial)}")
    print(f"Partial enrichment  : {len(partial)}")
    print(f"Failed              : {len(failed_coverage)}")
    print(f"Skipped cooldown    : {len(skipped)}")

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
        status = result.coverage_status

        print(
            f"{index:>2}. "
            f"{result.company_name:<28} "
            f"{result.elapsed_seconds:>7.1f}s "
            f"{result.jobs_fetched:>6} jobs "
            f"[{result.provider}, {status}]"
        )
        if result.coverage_note:
            print(f"    [COVERAGE] {result.coverage_note}")


def main() -> None:
    run_started = time.perf_counter()

    settings = _settings()
    max_jobs = _max_jobs(settings)

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
                result = CompanyRunResult(
                    company_id=company.id,
                    company_name=company.name,
                    provider=company.provider.type.value,
                    success=False,
                    coverage_status="failed",
                    listing_status="failed",
                    error=f"{type(exc).__name__}: {exc}",
                )

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

            if result.coverage_status == "partial":
                print(
                    f"    [COVERAGE] partial enrichment: "
                    f"resolved={result.enrichment_resolved}/"
                    f"{result.enrichment_candidates} "
                    f"unresolved={result.enrichment_unresolved} "
                    f"unstarted={result.enrichment_unstarted}"
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
        max_jobs,
        settings,
    )


if __name__ == "__main__":
    main()
