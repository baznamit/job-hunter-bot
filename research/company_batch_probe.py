import re
import sys
from urllib.parse import urljoin

import requests


_TIMEOUT = 30

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/127.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/json;q=0.9,*/*;q=0.8"
    ),
}


def _print_response(
    name: str,
    response: requests.Response,
) -> None:
    print(
        f"[BATCH-PROBE] {name}: "
        f"status={response.status_code} "
        f"final_url={response.url} "
        f"content_type="
        f"{response.headers.get('Content-Type')} "
        f"length={len(response.content)}",
        file=sys.stderr,
    )


def _interesting(
    name: str,
    text: str,
    base_url: str,
) -> None:
    patterns = (
        "phenom",
        "phncdn",
        "icims",
        "/api/",
        "graphql",
        "algolia",
        "workday",
        "search-results",
        "job-search",
        "__NEXT_DATA__",
    )

    lower = text.lower()

    for marker in patterns:
        if marker.lower() not in lower:
            continue

        print(
            f"[BATCH-PROBE] {name}: "
            f"FOUND marker={marker!r}",
            file=sys.stderr,
        )

        start = 0

        for _ in range(2):
            index = lower.find(
                marker.lower(),
                start,
            )

            if index == -1:
                break

            context = text[
                max(0, index - 500):
                index + 1500
            ].replace("\n", " ")

            print(
                f"[BATCH-PROBE] {name}: "
                f"CONTEXT={context[:2000]}",
                file=sys.stderr,
            )

            start = index + len(marker)

    urls = set(
        re.findall(
            r'https?://[^"\'\s<>\\]+',
            text,
            flags=re.IGNORECASE,
        )
    )

    for url in sorted(urls):
        lower_url = url.lower()

        if any(
            marker in lower_url
            for marker in (
                "api",
                "job",
                "career",
                "icims",
                "phenom",
                "phncdn",
                "workday",
            )
        ):
            print(
                f"[BATCH-PROBE] {name}: "
                f"CANDIDATE_URL={url[:1000]}",
                file=sys.stderr,
            )

    scripts = re.findall(
        r'<script[^>]+src=["\']([^"\']+)["\']',
        text,
        flags=re.IGNORECASE,
    )

    print(
        f"[BATCH-PROBE] {name}: "
        f"scripts={len(scripts)}",
        file=sys.stderr,
    )

    for src in scripts[:20]:
        print(
            f"[BATCH-PROBE] {name}: "
            f"SCRIPT={urljoin(base_url, src)}",
            file=sys.stderr,
        )


def probe_broadridge() -> None:
    name = "Broadridge"

    endpoint = (
        "https://broadridge.wd5.myworkdayjobs.com/"
        "wday/cxs/broadridge/Careers/jobs"
    )

    pages = []

    for offset in (0, 20):
        try:
            response = requests.post(
                endpoint,
                json={
                    "appliedFacets": {},
                    "limit": 20,
                    "offset": offset,
                    "searchText": "",
                },
                headers={
                    **_HEADERS,
                    "Content-Type": "application/json",
                },
                timeout=_TIMEOUT,
            )

            _print_response(
                f"{name} offset={offset}",
                response,
            )

            if response.status_code != 200:
                print(
                    f"[BATCH-PROBE] {name}: "
                    f"body={response.text[:1000]!r}",
                    file=sys.stderr,
                )
                return

            data = response.json()
            jobs = data.get("jobPostings") or []

            pages.append(jobs)

            print(
                f"[BATCH-PROBE] {name}: "
                f"offset={offset} "
                f"total={data.get('total')} "
                f"returned={len(jobs)}",
                file=sys.stderr,
            )

            for job in jobs[:3]:
                print(
                    f"[BATCH-PROBE] {name}: "
                    f"JOB title={job.get('title')!r} "
                    f"location="
                    f"{job.get('locationsText')!r} "
                    f"path={job.get('externalPath')!r}",
                    file=sys.stderr,
                )

        except Exception as exc:
            print(
                f"[BATCH-PROBE] {name}: "
                f"FAILED {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            return

    if len(pages) == 2:
        first = {
            job.get("externalPath")
            for job in pages[0]
        }

        second = {
            job.get("externalPath")
            for job in pages[1]
        }

        print(
            f"[BATCH-PROBE] {name}: "
            f"pages_different={first != second} "
            f"overlap={len(first & second)}",
            file=sys.stderr,
        )


def probe_html(
    name: str,
    url: str,
) -> None:
    try:
        response = requests.get(
            url,
            headers=_HEADERS,
            timeout=_TIMEOUT,
            allow_redirects=True,
        )

    except requests.RequestException as exc:
        print(
            f"[BATCH-PROBE] {name}: "
            f"FAILED {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return

    _print_response(
        name,
        response,
    )

    if response.status_code != 200:
        print(
            f"[BATCH-PROBE] {name}: "
            f"body={response.text[:1000]!r}",
            file=sys.stderr,
        )
        return

    _interesting(
        name,
        response.text,
        response.url,
    )


def main() -> None:
    probe_broadridge()

    probe_html(
        "HERE",
        (
            "https://careers.here.com/"
            "join/jobs/81789?lang=en-us"
        ),
    )

    probe_html(
        "BookMyShow",
        "https://in.bookmyshow.com/careers/",
    )

    probe_html(
        "Bank of America",
        (
            "https://careers.bankofamerica.com/"
            "en-us/job-search/india/"
            "q-software-engineer"
        ),
    )

    probe_html(
        "IDFC FIRST Bank",
        (
            "https://careers.idfcfirstbank.com/"
            "in/en/search-results"
            "?keywords=Software%20Engineer"
            "&from=0&s=1"
        ),
    )


if __name__ == "__main__":
    main()