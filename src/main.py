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
from src.filters import JobFilter, RejectionReason
from src.notifier import TelegramNotifier
from src.providers import AshbyAdapter, GreenhouseAdapter, LeverAdapter, WorkdayAdapter
from src.providers.exceptions import (
    ProviderNotFoundError,
    ProviderTemporaryError,
)
from src.store import SeenStore
from src.description_diagnostics import enrich_near_misses

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SEEN_FILE = _PROJECT_ROOT / "data" / "seen.json"
_SETTINGS_FILE = _PROJECT_ROOT / "config" / "settings.json"

_ADAPTERS = {
    ProviderType.GREENHOUSE: GreenhouseAdapter(),
    ProviderType.LEVER: LeverAdapter(),
    ProviderType.ASHBY: AshbyAdapter(),
    ProviderType.WORKDAY: WorkdayAdapter(),
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
            continue  # Provider not yet implemented (e.g. Workday).

        try:
            jobs = adapter.fetch_jobs(company)

        except ProviderNotFoundError as exc:
            print(
                f"  [STALE] {company.name}: ATS mapping appears invalid — {exc}",
                file=sys.stderr,
            )

            recovered_company = _recover_stale_provider(company)

            if recovered_company is None:
                print(
                    f"  [WARN] {company.name}: automatic ATS recovery failed",
                    file=sys.stderr,
                )
                continue

            recovered_adapter = _ADAPTERS.get(
                recovered_company.provider.type
            )

            if recovered_adapter is None:
                print(
                    f"  [WARN] {company.name}: recovered provider "
                    f"{recovered_company.provider.type.value} "
                    "has no adapter",
                    file=sys.stderr,
                )
                continue

            try:
                jobs = recovered_adapter.fetch_jobs(
                    recovered_company
                )

            except ProviderNotFoundError as retry_exc:
                print(
                    f"  [WARN] {company.name}: recovered ATS became "
                    f"invalid during retry — {retry_exc}",
                    file=sys.stderr,
                )
                continue

            except ProviderTemporaryError as retry_exc:
                print(
                    f"  [WARN] {company.name}: recovered ATS had a "
                    f"temporary failure — {retry_exc}",
                    file=sys.stderr,
                )
                continue

            except Exception as retry_exc:
                print(
                    f"  [WARN] {company.name}: recovered ATS fetch "
                    f"failed — {retry_exc}",
                    file=sys.stderr,
                )
                continue

            print(
                f"  [RECOVERED] {company.name}: jobs fetched using "
                f"{recovered_company.provider.type.value}",
                file=sys.stderr,
            )

        except ProviderTemporaryError as exc:
            print(
                f"  [WARN] {company.name}: temporary ATS failure — {exc}",
                file=sys.stderr,
            )
            continue

        except Exception as exc:
            print(
                f"  [WARN] {company.name}: fetch failed — {exc}",
                file=sys.stderr,
            )
            continue

        matching = [
            job
            for job in jobs
            if job_filter.should_include(job)
        ]

        diagnostics = job_filter.diagnose(
            jobs,
            sample_limit=5,
        )

        print(
            f"  {company.name}: "
            f"{len(jobs)} fetched, "
            f"{len(matching)} matching"
        )

        _print_filter_diagnostics(
            company.name,
            diagnostics,
        )

        enriched_near_misses = enrich_near_misses(
            jobs,
            job_filter,
            limit=20,
        )

        _print_enriched_near_misses(
            company.name,
            enriched_near_misses,
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

    message = _build_message(new_jobs, _max_jobs())

    try:
        notifier.send_message(message)
        store.mark_seen(new_jobs)
        print(f"Telegram notification sent ({len(new_jobs)} job(s)).")
    except Exception as exc:
        # Don't mark as seen — will retry on the next run.
        print(f"[ERROR] Notification failed: {exc}", file=sys.stderr)
        sys.exit(1)

def _print_filter_diagnostics(
    company_name: str,
    diagnostics,
) -> None:
    if diagnostics.total == 0:
        return
    has_samples = any(
        diagnostics.samples[reason]
        for reason in RejectionReason
    )

    if not has_samples and diagnostics.matched > 0:
        return
    print()
    print(f"  [FILTER-DIAG] {company_name}")
    print(f"    Fetched             : {diagnostics.total}")
    print(f"    Current matched     : {diagnostics.matched}")
    print(
        f"    Missing include     : "
        f"{diagnostics.include_keyword}"
    )
    print(
        f"    Excluded keyword    : "
        f"{diagnostics.excluded_keyword}"
    )
    print(
        f"    Location mismatch   : "
        f"{diagnostics.location}"
    )
    print(
        f"    Seniority mismatch  : "
        f"{diagnostics.seniority}"
    )

    labels = {
        RejectionReason.INCLUDE_KEYWORD:
            "MISSING INCLUDE KEYWORD",
        RejectionReason.EXCLUDED_KEYWORD:
            "EXCLUDED KEYWORD",
        RejectionReason.LOCATION:
            "LOCATION",
        RejectionReason.SENIORITY:
            "SENIORITY",
    }

    for reason, label in labels.items():
        samples = diagnostics.samples[reason]

        if not samples:
            continue

        print(f"    Useful near misses — {label}:")

        for index, job in enumerate(samples, 1):
            print(
                f"      {index}. {job.title} "
                f"| {job.location}"
            )

def _print_enriched_near_misses(
    company_name: str,
    near_misses,
) -> None:
    strong = [
        item
        for item in near_misses
        if item.strong
    ]

    if not strong:
        return

    print(
        f"  [DESCRIPTION-DIAG] {company_name}: "
        f"{len(strong)} strong near miss(es)"
    )

    for item in strong[:5]:
        signals = ", ".join(item.signals[:8])

        print(
            f"    - {item.job.title} "
            f"| {item.job.location}"
        )
        print(
            f"      rejected_by="
            f"{item.rejection_reason.value}"
        )
        print(
            f"      signals={signals}"
        )
        
if __name__ == "__main__":
    main()
