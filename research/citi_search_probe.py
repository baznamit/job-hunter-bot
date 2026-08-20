import re
import sys

import requests


_BASE = "https://jobs.citi.com"
_TIMEOUT = 30


def _headers():
    return {
        "User-Agent": (
            "Mozilla/5.0 "
            "(compatible; JobHunterBot/1.0)"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,"
            "application/json;q=0.9,*/*;q=0.8"
        ),
    }


def _probe(
    label: str,
    path: str,
    params: dict,
):
    response = requests.get(
        f"{_BASE}{path}",
        params=params,
        headers=_headers(),
        timeout=_TIMEOUT,
        allow_redirects=True,
    )

    print(
        f"[CITI-SEARCH] {label}: "
        f"status={response.status_code} "
        f"url={response.url} "
        f"length={len(response.content)}",
        file=sys.stderr,
    )

    text = response.text

    total_patterns = (
        r'([\d,]+)\s+Results',
        r'([\d,]+)\s+jobs?\s+found',
    )

    for pattern in total_patterns:
        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        )

        if match:
            print(
                f"[CITI-SEARCH] {label}: "
                f"total={match.group(1)}",
                file=sys.stderr,
            )
            break

    anchors = re.findall(
        r'<a\b([^>]*)>(.*?)</a>',
        text,
        flags=(
            re.IGNORECASE
            | re.DOTALL
        ),
    )

    jobs = []

    for attrs, body in anchors:
        id_match = re.search(
            r'data-job-id=["\']([^"\']+)["\']',
            attrs,
            flags=re.IGNORECASE,
        )

        href_match = re.search(
            r'href=["\']([^"\']+)["\']',
            attrs,
            flags=re.IGNORECASE,
        )

        if not id_match or not href_match:
            continue

        href = href_match.group(1)

        if "/job/" not in href.lower():
            continue

        jobs.append(
            (
                id_match.group(1),
                href,
                body,
            )
        )

    print(
        f"[CITI-SEARCH] {label}: "
        f"jobs={len(jobs)}",
        file=sys.stderr,
    )

    for job_id, href, body in jobs[:5]:
        title = re.sub(
            r"<[^>]+>",
            " ",
            body,
        )

        title = re.sub(
            r"\s+",
            " ",
            title,
        ).strip()

        print(
            f"[CITI-SEARCH] {label}: "
            f"JOB id={job_id} "
            f"title={title!r} "
            f"href={href}",
            file=sys.stderr,
        )


def main():
    tests = [
        (
            "keyword-mumbai",
            "/search-jobs",
            {
                "k": "Mumbai",
            },
        ),
        (
            "location-mumbai",
            "/search-jobs",
            {
                "l": "Mumbai",
            },
        ),
        (
            "keyword-java",
            "/search-jobs",
            {
                "k": "Java",
            },
        ),
        (
            "keyword-software-engineer",
            "/search-jobs",
            {
                "k": "Software Engineer",
            },
        ),
    ]

    for label, path, params in tests:
        _probe(
            label,
            path,
            params,
        )


if __name__ == "__main__":
    main()