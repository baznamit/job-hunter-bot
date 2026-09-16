from __future__ import annotations

import html
import re
from urllib.parse import urljoin

import requests


URL = (
    "https://careers.bankofamerica.com/"
    "en-us/job-search/india"
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
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/json;q=0.9,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def clean(value: str) -> str:
    return re.sub(
        r"\s+",
        " ",
        html.unescape(value),
    ).strip()


def show_contexts(
    text: str,
    marker: str,
) -> None:
    lower = text.lower()
    needle = marker.lower()

    start = 0
    count = 0

    while count < 10:
        index = lower.find(
            needle,
            start,
        )

        if index < 0:
            break

        context = text[
            max(0, index - 1000):
            index + 2500
        ]

        print(
            "[BOFA-PROBE] "
            f"marker={marker!r} "
            f"context={clean(context)[:3500]!r}"
        )

        start = index + len(marker)
        count += 1


def main() -> None:
    response = requests.get(
        URL,
        headers=HEADERS,
        timeout=TIMEOUT,
        allow_redirects=True,
    )

    print(
        "[BOFA-PROBE] "
        f"status={response.status_code} "
        f"final={response.url} "
        f"length={len(response.content)}"
    )

    response.raise_for_status()

    text = response.text

    # -------------------------------------------------
    # Pagination / result-count evidence
    # -------------------------------------------------

    for marker in (
        "Showing Results",
        "pagination",
        "next",
        "load more",
        "load-more",
        "page=",
        "pageNumber",
        "page-number",
        "offset",
        "aria-label=\"Next",
        "aria-label='Next",
        "job-search",
    ):
        show_contexts(
            text,
            marker,
        )

    # -------------------------------------------------
    # Every link that looks related to this search
    # -------------------------------------------------

    links = []

    for match in re.finditer(
        r"<a\b[^>]*>",
        text,
        flags=re.IGNORECASE,
    ):
        tag = match.group(0)

        href_match = re.search(
            r'href=["\']([^"\']+)["\']',
            tag,
            flags=re.IGNORECASE,
        )

        if not href_match:
            continue

        href = html.unescape(
            href_match.group(1)
        )

        lower = (
            tag + " " + href
        ).lower()

        if any(
            marker in lower
            for marker in (
                "job-search",
                "next",
                "pagination",
                "page",
            )
        ):
            links.append(
                (
                    tag,
                    urljoin(
                        response.url,
                        href,
                    ),
                )
            )

    print(
        f"[BOFA-PROBE] "
        f"interesting_links={len(links)}"
    )

    for tag, url in links[:100]:
        print(
            "[BOFA-PROBE] "
            f"LINK url={url!r} "
            f"tag={clean(tag)!r}"
        )

    # -------------------------------------------------
    # Buttons/data attributes
    # -------------------------------------------------

    buttons = re.findall(
        r"<button\b[^>]*>.*?</button>",
        text,
        flags=(
            re.IGNORECASE
            | re.DOTALL
        ),
    )

    print(
        f"[BOFA-PROBE] "
        f"buttons={len(buttons)}"
    )

    for button in buttons:
        lower = button.lower()

        if any(
            marker in lower
            for marker in (
                "next",
                "load",
                "page",
                "result",
            )
        ):
            print(
                "[BOFA-PROBE] "
                f"BUTTON={clean(button)[:2500]!r}"
            )

    # -------------------------------------------------
    # Script URLs
    # -------------------------------------------------

    scripts = re.findall(
        r'<script[^>]+src=["\']'
        r'([^"\']+)["\']',
        text,
        flags=re.IGNORECASE,
    )

    print(
        f"[BOFA-PROBE] scripts={len(scripts)}"
    )

    for src in scripts:
        url = urljoin(
            response.url,
            html.unescape(src),
        )

        print(
            f"[BOFA-PROBE] SCRIPT={url}"
        )

    # -------------------------------------------------
    # Current job-card boundaries.
    #
    # This will help us repair the location parser that
    # occasionally consumes the footer.
    # -------------------------------------------------

    cards = re.findall(
        r'<[^>]+class=["\'][^"\']*'
        r'job-search-tile[^"\']*["\'][^>]*>'
        r'.*?'
        r'(?=<[^>]+class=["\'][^"\']*'
        r'job-search-tile|\Z)',
        text,
        flags=(
            re.IGNORECASE
            | re.DOTALL
        ),
    )

    print(
        f"[BOFA-PROBE] "
        f"card_blocks={len(cards)}"
    )

    if cards:
        print(
            "[BOFA-PROBE] "
            f"LAST_CARD="
            f"{clean(cards[-1])[:7000]!r}"
        )


if __name__ == "__main__":
    main()