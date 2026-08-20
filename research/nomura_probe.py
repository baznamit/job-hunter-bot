import re
import sys
from urllib.parse import urljoin

import requests


_BASE_URL = "https://careers.nomura.com"

_LISTING_URL = (
    "https://careers.nomura.com/"
    "Nomura/go/Career-Opportunities-India/9050900/"
)

_TIMEOUT = 30


def _fetch(url: str) -> requests.Response:
    return requests.get(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 "
                "(compatible; JobHunterBot/1.0)"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,"
                "application/xml;q=0.9,*/*;q=0.8"
            ),
        },
        timeout=_TIMEOUT,
        allow_redirects=True,
    )


def _job_links(
    html: str,
    base_url: str,
) -> list[str]:
    links = re.findall(
        r'href=["\']([^"\']+)["\']',
        html,
        flags=re.IGNORECASE,
    )

    jobs = []

    for href in links:
        if "/Nomura/job/" not in href:
            continue

        url = urljoin(
            base_url,
            href,
        )

        if url not in jobs:
            jobs.append(url)

    return jobs


def _probe_page(
    offset: int,
) -> list[str]:
    if offset == 0:
        url = _LISTING_URL
    else:
        url = f"{_LISTING_URL}{offset}/"

    response = _fetch(url)

    print(
        f"[NOMURA-PROBE] "
        f"offset={offset} "
        f"status={response.status_code} "
        f"final_url={response.url} "
        f"body_length={len(response.content)}",
        file=sys.stderr,
    )

    if response.status_code != 200:
        print(
            "[NOMURA-PROBE] body="
            + repr(response.text[:1000]),
            file=sys.stderr,
        )
        return []

    jobs = _job_links(
        response.text,
        response.url,
    )

    print(
        f"[NOMURA-PROBE] "
        f"offset={offset} "
        f"job_links={len(jobs)}",
        file=sys.stderr,
    )

    for job in jobs[:5]:
        print(
            f"[NOMURA-PROBE] JOB={job}",
            file=sys.stderr,
        )

    return jobs


def main() -> None:
    page_1 = _probe_page(0)
    page_2 = _probe_page(100)

    overlap = (
        set(page_1)
        & set(page_2)
    )

    print(
        "[NOMURA-PROBE] "
        f"pages_different="
        f"{set(page_1) != set(page_2)} "
        f"overlap={len(overlap)}",
        file=sys.stderr,
    )

    if not page_1:
        return

    response = _fetch(
        page_1[0]
    )

    print(
        "[NOMURA-PROBE] "
        f"detail_status={response.status_code} "
        f"detail_url={response.url} "
        f"detail_length={len(response.content)}",
        file=sys.stderr,
    )

    html = response.text

    job_code_patterns = (
        r'Job\s+Code\s*:?\s*</?[^>]*>\s*([A-Za-z0-9_-]+)',
        r'Job\s+Code\s*:?\s*([A-Za-z0-9_-]+)',
        r'Requisition\s+(?:ID|No\.?)\s*:?\s*([A-Za-z0-9_-]+)',
    )

    for pattern in job_code_patterns:
        match = re.search(
            pattern,
            html,
            flags=re.IGNORECASE,
        )

        if not match:
            continue

        print(
            "[NOMURA-PROBE] "
            f"job_code={match.group(1)}",
            file=sys.stderr,
        )
        break


if __name__ == "__main__":
    main()