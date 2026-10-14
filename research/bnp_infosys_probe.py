
from __future__ import annotations

import re
from urllib.parse import urljoin

import requests

BASE = "https://career.infosys.com"

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
    "Referer": BASE + "/jobs",
}

SCRIPTS = [
    "/assets/js/env.js",
    "/runtime.js",
    "/main.js",
]

MARKERS = (
    "api",
    "baseUrl",
    "baseURL",
    "environment",
    "jobReferenceCode",
    "companyhiringtype",
    "countrycode",
    "joblist",
    "jobdesc",
    "searchJobs",
    "getJobs",
    "pagination",
    "pageSize",
    "graphql",
    "https://",
    "http://",
)

MAX_CONTEXTS = 5
MAX_SCRIPT_BYTES = 15_000_000


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def inspect_script(
    session: requests.Session,
    path: str,
) -> None:
    url = urljoin(BASE, path)

    print()
    print(f"[INF-JS] Fetching {url}")

    try:
        response = session.get(
            url,
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        print(
            f"[INF-JS] ERROR "
            f"{type(exc).__name__}: {exc}"
        )
        return

    print(
        f"[INF-JS] status={response.status_code} "
        f"bytes={len(response.content)} "
        f"type={response.headers.get('Content-Type')}"
    )

    if response.status_code != 200:
        print(
            f"[INF-JS] body="
            f"{response.text[:500]!r}"
        )
        return

    if len(response.content) > MAX_SCRIPT_BYTES:
        print("[INF-JS] SKIPPED: script too large")
        return

    text = response.text
    lower = text.lower()

    for marker in MARKERS:
        matches = list(
            re.finditer(
                re.escape(marker),
                lower,
                re.IGNORECASE,
            )
        )

        print(
            f"[INF-JS] marker={marker!r} "
            f"count={len(matches)}"
        )

        for match in matches[:MAX_CONTEXTS]:
            snippet = text[
                max(0, match.start() - 350):
                min(len(text), match.end() + 700)
            ]

            print(
                f"[INF-JS] CONTEXT "
                f"marker={marker!r} "
                f"text={clean(snippet)[:1000]!r}"
            )

    urls = set(
        re.findall(
            r'https?://[^"\'\s<>\\]+',
            text,
            flags=re.IGNORECASE,
        )
    )

    for candidate in sorted(urls):
        if any(
            term in candidate.lower()
            for term in (
                "api",
                "career",
                "job",
                "infosys",
                "graphql",
            )
        ):
            print(
                f"[INF-JS] CANDIDATE_URL "
                f"{candidate[:300]}"
            )


def main() -> None:
    with requests.Session() as session:
        session.headers.update(HEADERS)

        for path in SCRIPTS:
            inspect_script(session, path)


if __name__ == "__main__":
    main()
