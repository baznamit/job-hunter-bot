import html
import re
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
        f"[FINAL-PROBE] {name}: "
        f"{label} "
        f"status={response.status_code} "
        f"url={response.url} "
        f"content_type="
        f"{response.headers.get('Content-Type')} "
        f"length={len(response.content)}"
    )


def _contexts(
    name: str,
    text: str,
    markers: tuple[str, ...],
) -> None:
    lower = text.lower()

    for marker in markers:
        start = 0

        for _ in range(5):
            index = lower.find(
                marker.lower(),
                start,
            )

            if index < 0:
                break

            context = text[
                max(0, index - 500):
                index + 1800
            ]

            context = re.sub(
                r"\s+",
                " ",
                html.unescape(context),
            )

            print(
                f"[FINAL-PROBE] {name}: "
                f"marker={marker!r} "
                f"context={context[:2300]!r}"
            )

            start = index + len(marker)


def _print_links(
    name: str,
    base_url: str,
    text: str,
) -> None:
    links = set()

    for href in re.findall(
        r'href=["\']([^"\']+)["\']',
        text,
        flags=re.IGNORECASE,
    ):
        href = html.unescape(href)

        if href.startswith(
            (
                "#",
                "javascript:",
                "mailto:",
                "tel:",
                "data:",
            )
        ):
            continue

        url = urljoin(
            base_url,
            href,
        )

        lower = url.lower()

        if any(
            value in lower
            for value in (
                "job",
                "position",
                "career",
                "search",
                "apply",
            )
        ):
            links.add(url)

    print(
        f"[FINAL-PROBE] {name}: "
        f"interesting_links={len(links)}"
    )

    for url in sorted(links)[:30]:
        print(
            f"[FINAL-PROBE] {name}: "
            f"LINK={url}"
        )


# ---------------------------------------------------------
# MICROSOFT
# ---------------------------------------------------------

def probe_microsoft() -> None:
    name = "Microsoft"

    urls = (
        (
            "software-engineer",
            "https://apply.careers.microsoft.com/"
            "search?query=Software%20Engineer",
        ),
        (
            "java",
            "https://apply.careers.microsoft.com/"
            "search?query=Java",
        ),
        (
            "india",
            "https://apply.careers.microsoft.com/"
            "search?query=India",
        ),
    )

    for label, url in urls:
        response = _get(url)

        _summary(
            name,
            label,
            response,
        )

        if response.status_code != 200:
            continue

        _contexts(
            name,
            response.text,
            (
                "position",
                "location",
                "job",
                "page",
                "offset",
                "next",
                "total",
                "/api/",
            ),
        )

        _print_links(
            name,
            response.url,
            response.text,
        )


# ---------------------------------------------------------
# JUPITER / KEKA
# ---------------------------------------------------------

def probe_jupiter() -> None:
    name = "Jupiter"

    document_url = (
        "https://jupiter.keka.com/"
        "ats/documents/"
        "b5279857-cf81-4dde-a215-fc48957ee2b5/"
        "careerportal/"
        "18096d20247d4ecfa4efcf04875cbda6.html"
    )

    response = _get(
        document_url
    )

    _summary(
        name,
        "career-document",
        response,
    )

    if response.status_code != 200:
        return

    _contexts(
        name,
        response.text,
        (
            "/api/",
            "/ats/",
            "job",
            "opening",
            "position",
            "location",
            "department",
            "page",
            "offset",
            "skip",
            "take",
        ),
    )

    _print_links(
        name,
        response.url,
        response.text,
    )

    scripts = re.findall(
        r'<script[^>]+src=["\']([^"\']+)["\']',
        response.text,
        flags=re.IGNORECASE,
    )

    print(
        f"[FINAL-PROBE] Jupiter: "
        f"scripts={len(scripts)}"
    )

    for src in scripts[:10]:
        url = urljoin(
            response.url,
            html.unescape(src),
        )

        try:
            script_response = _get(
                url
            )
        except requests.RequestException as exc:
            print(
                f"[FINAL-PROBE] Jupiter: "
                f"SCRIPT_FAILED={url} "
                f"{type(exc).__name__}: {exc}"
            )
            continue

        _summary(
            name,
            "script",
            script_response,
        )

        if script_response.status_code == 200:
            _contexts(
                name,
                script_response.text,
                (
                    "/api/",
                    "/ats/",
                    "job",
                    "opening",
                    "position",
                ),
            )


# ---------------------------------------------------------
# PHONEPE
# ---------------------------------------------------------

def probe_phonepe() -> None:
    name = "PhonePe"

    runtime_url = (
        "https://www.phonepe.com/"
        "webstatic/14886/"
        "webpack-runtime-12264017310890117f23.js"
    )

    response = _get(
        runtime_url
    )

    _summary(
        name,
        "webpack-runtime",
        response,
    )

    if response.status_code != 200:
        return

    _contexts(
        name,
        response.text,
        (
            "4339",
            "job-openings",
        ),
    )

    # Gatsby's runtime contains the mapping required to
    # construct the real chunk filename. Print matching
    # JS-looking strings around chunk 4339.
    matches = re.findall(
        r'[^,"\']*4339[^,"\']*',
        response.text,
        flags=re.IGNORECASE,
    )

    for value in matches[:20]:
        print(
            f"[FINAL-PROBE] PhonePe: "
            f"CHUNK_CONTEXT={value[:1000]!r}"
        )


# ---------------------------------------------------------
# ATLASSIAN
# ---------------------------------------------------------

def probe_atlassian() -> None:
    name = "Atlassian"

    response = _get(
        "https://www.atlassian.com/"
        "company/careers/all-jobs"
    )

    _summary(
        name,
        "all-jobs",
        response,
    )

    if response.status_code != 200:
        return

    scripts = re.findall(
        r'<script[^>]+src=["\']([^"\']+)["\']',
        response.text,
        flags=re.IGNORECASE,
    )

    for src in scripts:
        url = urljoin(
            response.url,
            html.unescape(src),
        )

        lower = url.lower()

        if not any(
            value in lower
            for value in (
                "career",
                "job",
                "lever",
                "main",
            )
        ):
            continue

        try:
            script_response = _get(
                url
            )
        except requests.RequestException:
            continue

        _summary(
            name,
            "career-script",
            script_response,
        )

        if script_response.status_code != 200:
            continue

        _contexts(
            name,
            script_response.text,
            (
                "lever",
                "job",
                "career",
                "/api/",
                "position",
                "location",
            ),
        )


def main() -> None:
    probe_microsoft()
    probe_jupiter()
    probe_phonepe()
    probe_atlassian()


if __name__ == "__main__":
    main()