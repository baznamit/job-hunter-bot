from providers.greenhouse import GreenhouseProvider
from filters import JobFilter


def main():

    provider = GreenhouseProvider()
    job_filter = JobFilter()

    jobs = provider.fetch_jobs()

    matching_jobs = []

    for job in jobs:

        if job_filter.should_include(job.title):
            matching_jobs.append(job)

    print()
    print("=" * 80)
    print(f"Total Jobs Fetched   : {len(jobs)}")
    print(f"Matching Jobs Found  : {len(matching_jobs)}")
    print("=" * 80)
    print()

    for job in matching_jobs:

        print(f"Company : {job.company}")
        print(f"Title   : {job.title}")
        print(f"Location: {job.location}")
        print(f"Apply   : {job.url}")
        print("-" * 80)


if __name__ == "__main__":
    main()