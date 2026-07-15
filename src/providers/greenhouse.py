import json
import requests

from models import Job


class GreenhouseProvider:

    def __init__(self):
        with open("config/companies.json", "r", encoding="utf-8") as file:
            config = json.load(file)

        self.boards = config.get("greenhouse", [])

    def fetch_jobs(self):

        all_jobs = []

        for company in self.boards:

            board = company["board"]
            company_name = company["company"]

            url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs"

            print(f"Fetching {company_name}...")

            try:

                response = requests.get(url, timeout=20)

                if response.status_code != 200:
                    print(f"Failed: {company_name}")
                    continue

                data = response.json()

                for job in data["jobs"]:

                    location = "Unknown"

                    if job.get("location"):
                        location = job["location"].get("name", "Unknown")

                    all_jobs.append(
                        Job(
                            title=job["title"],
                            company=company_name,
                            location=location,
                            url=job["absolute_url"],
                            source="Greenhouse"
                        )
                    )

            except Exception as e:
                print(f"Error fetching {company_name}: {e}")

        return all_jobs