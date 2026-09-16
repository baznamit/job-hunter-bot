from __future__ import annotations

import requests


BASE = "https://careers.bankofamerica.com"
ENDPOINT = f"{BASE}/services/jobssearchservlet"

TIMEOUT = 30

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/127.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


def request(
    label: str,
    params: dict[str, str | int],
) -> dict | None:
    response = requests.get(
        ENDPOINT,
        params=params,
        headers=HEADERS,
        timeout=TIMEOUT,
    )

    print()
    print(
        f"[BOFA-PROBE] {label}: "
        f"status={response.status_code} "
        f"url={response.url} "
        f"content_type="
        f"{response.headers.get('Content-Type')} "
        f"length={len(response.content)}"
    )

    if response.status_code != 200:
        print(
            f"[BOFA-PROBE] {label}: "
            f"body={response.text[:1000]!r}"
        )
        return None

    try:
        data = response.json()
    except ValueError:
        print(
            f"[BOFA-PROBE] {label}: "
            "NON-JSON "
            f"body={response.text[:1000]!r}"
        )
        return None

    print(
        f"[BOFA-PROBE] {label}: "
        f"keys={list(data.keys())}"
    )

    print(
        f"[BOFA-PROBE] {label}: "
        f"totalMatches={data.get('totalMatches')}"
    )

    jobs = data.get("jobsList") or []

    print(
        f"[BOFA-PROBE] {label}: "
        f"jobs={len(jobs)}"
    )

    for job in jobs[:5]:
        print(
            "[BOFA-PROBE] JOB "
            f"id={job.get('jobRequisitionId')!r} "
            f"title={job.get('postingTitle')!r} "
            f"location={job.get('location')!r} "
            f"keys={list(job.keys())}"
        )

    return data


def ids(
    data: dict | None,
) -> list[str]:
    if not data:
        return []

    result = []

    for job in data.get("jobsList") or []:
        value = (
            job.get("jobRequisitionId")
            or job.get("requisitionId")
            or job.get("id")
        )

        if value is not None:
            result.append(str(value))

    return result


def compare(
    label: str,
    first: dict | None,
    second: dict | None,
) -> None:
    first_ids = ids(first)
    second_ids = ids(second)

    print()
    print(
        f"[BOFA-PROBE] {label}: "
        f"first={len(first_ids)} "
        f"second={len(second_ids)} "
        f"overlap="
        f"{len(set(first_ids) & set(second_ids))}"
    )

    print(
        f"[BOFA-PROBE] {label}: "
        f"first_ids={first_ids[:10]}"
    )

    print(
        f"[BOFA-PROBE] {label}: "
        f"second_ids={second_ids[:10]}"
    )


def main() -> None:

    # Baseline India request.
    page_1 = request(
        "india-0-10",
        {
            "country": "India",
            "start": 0,
            "rows": 10,
            "search": "jobsByCountry",
        },
    )

    # Interpretation A:
    # rows is an ending pagination pointer.
    page_2_pointer = request(
        "india-10-20",
        {
            "country": "India",
            "start": 10,
            "rows": 20,
            "search": "jobsByCountry",
        },
    )

    page_3_pointer = request(
        "india-20-30",
        {
            "country": "India",
            "start": 20,
            "rows": 30,
            "search": "jobsByCountry",
        },
    )

    # Interpretation B:
    # rows is simply page size.
    page_2_size = request(
        "india-10-10",
        {
            "country": "India",
            "start": 10,
            "rows": 10,
            "search": "jobsByCountry",
        },
    )

    compare(
        "pointer-page1-v-page2",
        page_1,
        page_2_pointer,
    )

    compare(
        "pointer-page2-v-page3",
        page_2_pointer,
        page_3_pointer,
    )

    compare(
        "size-page1-v-page2",
        page_1,
        page_2_size,
    )


if __name__ == "__main__":
    main()