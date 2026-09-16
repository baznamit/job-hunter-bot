from __future__ import annotations

import re

import requests


URL = (
    "https://careers.bankofamerica.com/"
    "etc.clientlibs/careers/clientlibs/"
    "clientlib-base.js"
)

TIMEOUT = 30

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/127.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
}


MARKERS = (
    "getAllJobs",
    "start=",
    "rows=",
    "pagination",
    "span_results",
    "js-mp-job-search-results-listing",
    "job-search-results",
    "job-search-filter",
    "search=",
    "$.ajax",
    "ajax(",
    "fetch(",
    "XMLHttpRequest",
)


def clean(
    value: str,
) -> str:
    return re.sub(
        r"\s+",
        " ",
        value,
    ).strip()


def contexts(
    text: str,
    marker: str,
) -> None:
    lower = text.lower()
    needle = marker.lower()

    start = 0

    for _ in range(12):
        index = lower.find(
            needle,
            start,
        )

        if index < 0:
            break

        context = text[
            max(0, index - 1800):
            index + 4500
        ]

        print(
            "[BOFA-API] "
            f"marker={marker!r} "
            f"context="
            f"{clean(context)[:6300]!r}"
        )

        start = (
            index
            + len(marker)
        )


def main() -> None:
    response = requests.get(
        URL,
        headers=HEADERS,
        timeout=TIMEOUT,
    )

    print(
        "[BOFA-API] "
        f"status={response.status_code} "
        f"url={response.url} "
        f"length={len(response.content)}"
    )

    response.raise_for_status()

    text = response.text

    for marker in MARKERS:
        contexts(
            text,
            marker,
        )

    # Extract URL-looking strings around careers/search.
    urls = sorted(
        set(
            re.findall(
                r'["\']'
                r'([^"\']*'
                r'(?:job-search|search|jobs)'
                r'[^"\']*)'
                r'["\']',
                text,
                flags=re.IGNORECASE,
            )
        )
    )

    print(
        "[BOFA-API] "
        f"url_strings={len(urls)}"
    )

    for url in urls[:100]:
        print(
            f"[BOFA-API] URL={url!r}"
        )


if __name__ == "__main__":
    main()