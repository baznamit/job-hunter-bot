import json

from providers.greenhouse import GreenhouseProvider
from filters import JobFilter
from notifier import TelegramNotifier


def build_summary_message(jobs, max_jobs):

    if not jobs:
        return (
            "🤖 Job Hunter\n\n"
            "No matching jobs found."
        )

    lines = []

    lines.append("🚀 Job Hunter")
    lines.append("")
    lines.append(f"Found {len(jobs)} matching job(s)")
    lines.append("")

    jobs_to_show = jobs[:max_jobs]

    for index, job in enumerate(jobs_to_show, start=1):

        lines.append(f"{index}. {job.company}")
        lines.append(f"💼 {job.title}")
        lines.append(f"📍 {job.location}")
        lines.append(job.url)
        lines.append("")

    remaining = len(jobs) - len(jobs_to_show)

    if remaining > 0:
        lines.append(f"...and {remaining} more matching job(s).")

    return "\n".join(lines)


def load_max_jobs():

    with open("config/settings.json", "r", encoding="utf-8") as file:
        settings = json.load(file)

    return settings["telegram"]["max_jobs_per_message"]


def main():

    provider = GreenhouseProvider()
    job_filter = JobFilter()
    notifier = TelegramNotifier()

    jobs = provider.fetch_jobs()

    matching_jobs = []

    for job in jobs:

        if job_filter.should_include(job):
            matching_jobs.append(job)

    print()
    print("=" * 80)
    print(f"Total Jobs Fetched : {len(jobs)}")
    print(f"Matching Jobs      : {len(matching_jobs)}")
    print("=" * 80)
    print()

    for job in matching_jobs:

        print(f"✓ {job.company}")
        print(f"  {job.title}")
        print(f"  {job.location}")
        print()

    max_jobs = load_max_jobs()

    message = build_summary_message(
        matching_jobs,
        max_jobs
    )

    notifier.send_message(message)

    print("Telegram notification sent.")


if __name__ == "__main__":
    main()