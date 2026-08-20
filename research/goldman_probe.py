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


def _context(
    text: str,
    needle: str,
    radius: int = 2500,
) -> str | None:
    index = text.find(needle)

    if index == -1:
        return None

    left = max(0, index - radius)
    right = min(
        len(text),
        index + len(needle) + radius,
    )

    return text[left:right].replace(
        "\n",
        " ",
    )


def probe_goldman() -> None:
    response = _fetch(_URL)
    html = response.text

    print(
        f"[GOLDMAN-PROBE] final_url={response.url}",
        file=sys.stderr,
    )

    # Next.js can load chunks both directly from script tags and
    # indirectly through build manifests.
    urls: set[str] = set()

    for src in re.findall(
        r'<script[^>]+src=["\']([^"\']+)["\']',
        html,
        flags=re.IGNORECASE,
    ):
        urls.add(
            urljoin(response.url, src)
        )

    manifest_paths = re.findall(
        r'["\']([^"\']*(?:_buildManifest|'
        r'_ssgManifest)[^"\']*\.js)["\']',
        html,
    )

    for path in manifest_paths:
        manifest_url = urljoin(
            response.url,
            path,
        )

        try:
            manifest = _fetch(
                manifest_url
            ).text
        except requests.RequestException:
            continue

        for chunk in re.findall(
            r'["\']([^"\']+\.js)["\']',
            manifest,
        ):
            urls.add(
                urljoin(
                    manifest_url,
                    chunk,
                )
            )

    print(
        f"[GOLDMAN-PROBE] inspecting "
        f"{len(urls)} JS asset(s)",
        file=sys.stderr,
    )

    needles = (
        "GetRoles",
        "GetRoleFilters",
        "GetRoleSearchFiltersCount",
    )

    for script_url in sorted(urls):
        try:
            script = _fetch(
                script_url
            ).text
        except requests.RequestException as exc:
            print(
                f"[GOLDMAN-PROBE] fetch failed "
                f"{script_url}: {exc}",
                file=sys.stderr,
            )
            continue

        matched = False

        for needle in needles:
            context = _context(
                script,
                needle,
            )

            if context is None:
                continue

            if not matched:
                print(
                    "[GOLDMAN-PROBE] "
                    f"QUERY_SCRIPT={script_url}",
                    file=sys.stderr,
                )
                matched = True

            print(
                f"[GOLDMAN-PROBE] "
                f"QUERY_CONTEXT={needle}",
                file=sys.stderr,
            )

            print(
                f"[GOLDMAN-PROBE] {context}",
                file=sys.stderr,
            )

        # Also specifically look for gql-tagged operations.
        for match in re.finditer(
            r'(?:query\s+GetRoles|'
            r'GetRoles\s*\()',
            script,
        ):
            left = max(
                0,
                match.start() - 3000,
            )
            right = min(
                len(script),
                match.end() + 5000,
            )

            print(
                "[GOLDMAN-PROBE] "
                "GET_ROLES_DEFINITION",
                file=sys.stderr,
            )
            print(
                "[GOLDMAN-PROBE] "
                + script[left:right].replace(
                    "\n",
                    " ",
                ),
                file=sys.stderr,
            )


if __name__ == "__main__":
    probe_goldman()