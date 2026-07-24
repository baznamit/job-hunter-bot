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
from research.loader import load_registry
from src.filters import JobFilter
from src.notifier import TelegramNotifier
from src.providers import AshbyAdapter, GreenhouseAdapter, LeverAdapter, WorkdayAdapter
from src.store import SeenStore

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SEEN_FILE = _PROJECT_ROOT / "data" / "seen.json"
_SETTINGS_FILE = _PROJECT_ROOT / "config" / "settings.json"

_ADAPTERS = {
    ProviderType.GREENHOUSE: GreenhouseAdapter(),
    ProviderType.LEVER: LeverAdapter(),
    ProviderType.ASHBY: AshbyAdapter(),
    ProviderType.WORKDAY: WorkdayAdapter(),
}


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
        except Exception as exc:
            print(f"  [WARN] {company.name}: fetch failed — {exc}", file=sys.stderr)
            continue

        matching = [job for job in jobs if job_filter.should_include(job)]
        print(f"  {company.name}: {len(jobs)} fetched, {len(matching)} matching")
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


if __name__ == "__main__":
    main()
