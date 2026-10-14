
from __future__ import annotations

import requests

API = (
    "https://careers.hcltech.com"
    "/services/recruiting/v1/jobs"
)

BASE_PAYLOAD = {
    "locale": "en_US",
    "pageNumber": 0,
    "sortBy": "",
    "keywords": "",
    "location": "",
    "facetFilters": {},
    "categoryId": 0,
    "brand": "",
    "alertId": "",
    "rcmCandidateId": "",
    "skills": [],
}

LOCATIONS = [
    "",
    "Mumbai",
    "Navi Mumbai",
    "Bengaluru",
    "Bangalore",
    "India",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Origin": "https://careers.hcltech.com",
    "Referer": "https://careers.hcltech.com/search/",
}


def main():
    with requests.Session() as session:
        session.headers.update(HEADERS)

        for location in LOCATIONS:
            payload = dict(BASE_PAYLOAD)
            payload["location"] = location

            label = location or "ALL"

            try:
                response = session.post(
                    API,
                    json=payload,
                    timeout=(10, 30),
                )

                print(
                    f"\n[HCL-LOCATION] "
                    f"location={label!r} "
                    f"status={response.status_code}"
                )

                response.raise_for_status()

                data = response.json()

                records = data.get(
                    "jobSearchResult", []
                )

                print(
                    f"[HCL-LOCATION] "
                    f"total={data.get('totalJobs')} "
                    f"page_records={len(records)}"
                )

                for record in records[:5]:
                    job = record.get(
                        "response", {}
                    )

                    print(
                        f"[HCL-LOCATION] JOB "
                        f"id={job.get('id')} "
                        f"title={job.get('unifiedStandardTitle')} "
                        f"city={job.get('custprimecity')} "
                        f"country={job.get('custCountryRegion')}"
                    )

            except (
                requests.RequestException,
                ValueError,
                AttributeError,
            ) as exc:
                print(
                    f"[HCL-LOCATION] "
                    f"ERROR {type(exc).__name__}: {exc}"
                )


if __name__ == "__main__":
    main()
