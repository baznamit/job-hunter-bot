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
    "PhonePe": (
        "https://www.phonepe.com/en/careers.html"
    ),
    "Atlassian": (
        "https://www.atlassian.com/company/careers"
    ),
    "Deutsche Bank": (
        "https://careers.db.com/"
    ),
    "Microsoft": (
        "https://careers.microsoft.com/"
    ),
    "Jupiter": (
        "https://jupiter.money/careers/"
    ),
    "CoinDCX": (
        "https://coindcx.com/careers/"
    ),
    "Zepto": (
        "https://www.zeptonow.com/careers"
    ),
}


_MARKERS = (
    "greenhouse",
    "lever.co",
    "ashby",
    "workday",
    "myworkdayjobs",
    "oraclecloud",
    "successfactors",
    "smartrecruiters",
    "icims",
    "phenom",
    "eightfold",
    "talentbrew",
    "radancy",
    "algolia",
    "graphql",
    "/api/",
    "jobs/search",
    "search-jobs",
)


def _fetch(
    url: str,
) -> requests.Response:
    return requests.get(
        url,
        headers=_HEADERS,
        timeout=_TIMEOUT,
        allow_redirects=True,
    )


def _print_contexts(
    name: str,
    text: str,
) -> None:
    lower = text.lower()

    for marker in _MARKERS:
        start = 0
        printed = 0

        while printed < 2:
            index = lower.find(
                marker.lower(),
                start,
            )

            if index < 0:
                break

            context = text[
                max(0, index - 400):
                index + 1000
            ]

            context = re.sub(
                r"\s+",
                " ",
                context,
            )

            print(
                f"[STALE-PROBE] {name}: "
                f"marker={marker!r} "
                f"context={context[:1400]!r}"
            )

            start = (
                index
                + len(marker)
            )
            printed += 1


def _interesting_urls(
    name: str,
    text: str,
    base_url: str,
) -> list[str]:
    urls: set[str] = set()

    for href in re.findall(
        r'(?:href|src)=["\']([^"\']+)["\']',
        text,
        flags=re.IGNORECASE,
    ):
        url = urljoin(
            base_url,
            href,
        )

        lower = url.lower()

        if any(
            marker in lower
            for marker in (
                "career",
                "job",
                "workday",
                "greenhouse",
                "lever",
                "ashby",
                "oracle",
                "icims",
                "phenom",
                "eightfold",
                "smartrecruiters",
                "api",
            )
        ):
            urls.add(url)

    result = sorted(urls)

    print(
        f"[STALE-PROBE] {name}: "
        f"interesting_urls={len(result)}"
    )

    for url in result[:30]:
        print(
            f"[STALE-PROBE] {name}: "
            f"URL={url}"
        )

    return result


def _probe_linked_pages(
    name: str,
    urls: list[str],
) -> None:
    for url in urls[:10]:
        try:
            response = _fetch(url)

        except requests.RequestException as exc:
            print(
                f"[STALE-PROBE] {name}: "
                f"LINK_FAILED url={url} "
                f"error={type(exc).__name__}: {exc}"
            )
            continue

        print(
            f"[STALE-PROBE] {name}: "
            f"LINK status={response.status_code} "
            f"url={url} "
            f"final={response.url} "
            f"content_type="
            f"{response.headers.get('Content-Type')} "
            f"length={len(response.content)}"
        )

        if response.status_code == 200:
            _print_contexts(
                name,
                response.text,
            )


def probe_company(
    name: str,
    url: str,
) -> None:
    print()
    print(
        f"[STALE-PROBE] {name}: START "
        f"url={url}"
    )

    try:
        response = _fetch(url)

    except requests.RequestException as exc:
        print(
            f"[STALE-PROBE] {name}: "
            f"FETCH_FAILED "
            f"{type(exc).__name__}: {exc}"
        )
        return

    print(
        f"[STALE-PROBE] {name}: "
        f"status={response.status_code} "
        f"final_url={response.url} "
        f"content_type="
        f"{response.headers.get('Content-Type')} "
        f"server="
        f"{response.headers.get('Server')} "
        f"length={len(response.content)}"
    )

    print(
        f"[STALE-PROBE] {name}: "
        f"preview="
        f"{response.text[:500]!r}"
    )

    if response.status_code != 200:
        return

    _print_contexts(
        name,
        response.text,
    )

    urls = _interesting_urls(
        name,
        response.text,
        response.url,
    )

    _probe_linked_pages(
        name,
        urls,
    )


def main() -> None:
    for name, url in (
        _COMPANIES.items()
    ):
        probe_company(
            name,
            url,
        )


if __name__ == "__main__":
    main()