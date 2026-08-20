import re
import sys
from urllib.parse import urljoin

import requests


_URL = "https://higher.gs.com/results"
_TIMEOUT = 30


def _fetch(url: str) -> requests.Response:
    response = requests.get(
        url,
        timeout=_TIMEOUT,
        allow_redirects=True,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (compatible; JobHunterBot/1.0)"
            ),
            "Accept": "*/*",
        },
    )
    response.raise_for_status()
    return response


def _print_context(
    text: str,
    needle: str,
    source: str,
    radius: int = 700,
) -> None:
    lower = text.lower()
    start = 0
    found = 0

    while found < 5:
        index = lower.find(
            needle.lower(),
            start,
        )

        if index == -1:
            break

        left = max(0, index - radius)
        right = min(
            len(text),
            index + len(needle) + radius,
        )

        context = text[left:right]
        context = context.replace("\n", " ")

        print(
            f"[GOLDMAN-PROBE] CONTEXT "
            f"source={source} "
            f"needle={needle!r}",
            file=sys.stderr,
        )
        print(
            f"[GOLDMAN-PROBE] {context}",
            file=sys.stderr,
        )

        found += 1
        start = index + len(needle)


def probe_goldman() -> None:
    response = _fetch(_URL)

    print(
        f"[GOLDMAN-PROBE] final_url={response.url}",
        file=sys.stderr,
    )

    html = response.text

    script_sources = re.findall(
        r'<script[^>]+src=["\']([^"\']+)["\']',
        html,
        flags=re.IGNORECASE,
    )

    print(
        f"[GOLDMAN-PROBE] "
        f"scripts={len(script_sources)}",
        file=sys.stderr,
    )

    needles = (
        "/gateway/api/v1/graphql",
        "/api/v2/",
        "operationName",
        "query ",
        "mutation ",
        "roles",
        "searchRoles",
        "jobSearch",
        "jobResults",
        "pageSize",
        "pageNumber",
        "offset",
        "limit",
    )

    for src in script_sources:
        script_url = urljoin(
            response.url,
            src,
        )

        try:
            script_response = _fetch(
                script_url
            )
        except requests.RequestException as exc:
            print(
                f"[GOLDMAN-PROBE] script failed "
                f"{script_url}: {exc}",
                file=sys.stderr,
            )
            continue

        script = script_response.text

        interesting = any(
            needle.lower() in script.lower()
            for needle in (
                "/gateway/api/v1/graphql",
                "/api/v2/",
            )
        )

        if not interesting:
            continue

        print(
            f"[GOLDMAN-PROBE] "
            f"interesting_script={script_url}",
            file=sys.stderr,
        )

        for needle in needles:
            if needle.lower() in script.lower():
                _print_context(
                    script,
                    needle,
                    script_url,
                )


if __name__ == "__main__":
    probe_goldman()