import html
import re
from urllib.parse import urljoin

import requests

_TIMEOUT = 25

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

_COMPANIES = {
    "Freshworks": {
        "career": (
            "https://careers.freshworks.com/"
        ),
        "old": (
            "https://api.lever.co/v0/"
            "postings/freshworks?mode=json"
        ),
    },
    "Navi": {
        "career": (
            "https://navi.com/careers/"
        ),
        "old": (
            "https://api.ashbyhq.com/"
            "posting-api/job-board/navi"
        ),
    },
}

_MARKERS = (
    "greenhouse",
    "lever",
    "ashby",
    "workday",
    "myworkdayjobs",
    "smartrecruiters",
    "successfactors",
    "eightfold",
    "keka",
    "oraclecloud",
    "icims",
    "phenom",
    "/api/",
    "graphql",
    "job",
    "career",
)

def _get(
    url: str,
) -> requests.Response:
    return requests.get(
        url,
        headers=_HEADERS,
        timeout=_TIMEOUT,
        allow_redirects=True,
    )

def _summary(
    name: str,
    label: str,
    response: requests.Response,
) -> None:
    print(
        f"[EMPTY-PROBE] {name}: "
        f"{label} "
        f"status={response.status_code} "
        f"final={response.url} "
        f"content_type="
        f"{response.headers.get('Content-Type')} "
        f"server="
        f"{response.headers.get('Server')} "
        f"length={len(response.content)}"
    )

def _contexts(
    name: str,
    text: str,
) -> None:
    lower = text.lower()

    for marker in _MARKERS:
        start = 0
        count = 0

        while count < 3:
            index = lower.find(
                marker.lower(),
                start,
            )

            if index < 0:
                break

            context = text[
                max(0, index - 400):
                index + 1200
            ]

            context = re.sub(
                r"\s+",
                " ",
                html.unescape(context),
            )

            print(
                f"[EMPTY-PROBE] {name}: "
                f"marker={marker!r} "
                f"context="
                f"{context[:1600]!r}"
            )

            start = (
                index
                + len(marker)
            )
            count += 1

def _links(
    name: str,
    base_url: str,
    text: str,
) -> None:
    urls: set[str] = set()

    for value in re.findall(
        r'(?:href|src)=["\']'
        r'([^"\']+)["\']',
        text,
        flags=re.IGNORECASE,
    ):
        value = html.unescape(
            value
        )

        if value.startswith(
            (
                "#",
                "data:",
                "javascript:",
                "mailto:",
                "tel:",
            )
        ):
            continue

        url = urljoin(
            base_url,
            value,
        )

        lower = url.lower()

        if any(
            marker in lower
            for marker in (
                "career",
                "job",
                "lever",
                "ashby",
                "workday",
                "greenhouse",
                "eightfold",
                "api",
            )
        ):
            urls.add(url)

    print(
        f"[EMPTY-PROBE] {name}: "
        f"interesting_links={len(urls)}"
    )

    for url in sorted(urls)[:30]:
        print(
            f"[EMPTY-PROBE] {name}: "
            f"LINK={url}"
        )

def probe(
    name: str,
    config: dict,
) -> None:
    print()
    print(
        f"[EMPTY-PROBE] {name}: START"
    )

    old = _get(
        config["old"]
    )

    _summary(
        name,
        "old-provider",
        old,
    )

    print(
        f"[EMPTY-PROBE] {name}: "
        f"old_body={old.text[:1000]!r}"
    )

    career = _get(
        config["career"]
    )

    _summary(
        name,
        "career",
        career,
    )

    if career.status_code != 200:
        print(
            f"[EMPTY-PROBE] {name}: "
            f"career_body="
            f"{career.text[:1000]!r}"
        )
        return

    _contexts(
        name,
        career.text,
    )

    _links(
        name,
        career.url,
        career.text,
    )

def main() -> None:
    for name, config in (
        _COMPANIES.items()
    ):
        try:
            probe(
                name,
                config,
            )
        except requests.RequestException as exc:
            print(
                f"[EMPTY-PROBE] {name}: "
                f"FAILED "
                f"{type(exc).__name__}: {exc}"
            )

if __name__ == "__main__":
    main()
