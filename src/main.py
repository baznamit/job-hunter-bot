from providers.greenhouse import GreenhouseProvider
from filters import JobFilter
from notifier import TelegramNotifier


def main():

    provider = GreenhouseProvider()
    job_filter = JobFilter()
    notifier = TelegramNotifier()

    jobs = provider.fetch_jobs()

    matching_jobs = []

    for job in jobs:

        if job_filter.should_include(job.title):
            matching_jobs.append(job)

    print()
    print("=" * 80)
    print(f"Total Jobs Fetched  : {len(jobs)}")
    print(f"Matching Jobs Found : {len(matching_jobs)}")
    print("=" * 80)
    print()

    if len(matching_jobs) == 0:

        print("No matching jobs found.")

        notifier.send_message(
            "❌ Job Hunter\n\nNo matching jobs found today."
        )

        return

    for job in matching_jobs:

        print(f"{job.company} - {job.title}")

        message = (
            "🚀 New Matching Job\n\n"
            f"🏢 Company: {job.company}\n"
            f"💼 Role: {job.title}\n"
            f"📍 Location: {job.location}\n"
            f"🌐 Source: {job.source}\n\n"
            f"Apply:\n{job.url}"
        )

        notifier.send_message(message)


if __name__ == "__main__":
    main()