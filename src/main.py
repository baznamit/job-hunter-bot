from providers.greenhouse import GreenhouseProvider


def main():

    provider = GreenhouseProvider()

    jobs = provider.fetch_jobs()

    print()
    print("=" * 80)
    print(f"Total Jobs Found: {len(jobs)}")
    print("=" * 80)
    print()

    for job in jobs:

        print(f"Company : {job.company}")
        print(f"Title    : {job.title}")
        print(f"Location : {job.location}")
        print(f"Source   : {job.source}")
        print(f"Apply    : {job.url}")
        print("-" * 80)


if __name__ == "__main__":
    main()