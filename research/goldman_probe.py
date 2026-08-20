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
            "Accept": (
                "text/html,application/xhtml+xml,"
                "application/json"
            ),
        },
    )

    response.raise_for_status()
    return response


def probe_goldman() -> None:
    response = _fetch(_URL)

    print(
        f"[GOLDMAN-PROBE] final_url={response.url}",
        file=sys.stderr,
    )
    print(
        f"[GOLDMAN-PROBE] status={response.status_code}",
        file=sys.stderr,
    )
    print(
        "[GOLDMAN-PROBE] "
        f"content_type={response.headers.get('Content-Type')}",
        file=sys.stderr,
    )

    html = response.text

    patterns = (
        r'https?://[^"\'\s<>]+/api/[^"\'\s<>]*',
        r'https?://[^"\'\s<>]+graphql[^"\'\s<>]*',
        r'https?://[^"\'\s<>]+jobs?[^"\'\s<>]*',
        r'https?://[^"\'\s<>]+roles?[^"\'\s<>]*',
        r'["\'](/[^"\']*api[^"\']*)["\']',
        r'["\'](/[^"\']*graphql[^"\']*)["\']',
    )

    matches: set[str] = set()

    for pattern in patterns:
        for match in re.findall(
            pattern,
            html,
            flags=re.IGNORECASE,
        ):
            matches.add(
                urljoin(
                    response.url,
                    match,
                )
            )

    print(
        f"[GOLDMAN-PROBE] found "
        f"{len(matches)} API/reference candidate(s)",
        file=sys.stderr,
    )

    for match in sorted(matches):
        print(
            f"[GOLDMAN-PROBE] {match[:500]}",
            file=sys.stderr,
        )

    script_sources = re.findall(
        r'<script[^>]+src=["\']([^"\']+)["\']',
        html,
        flags=re.IGNORECASE,
    )

    print(
        f"[GOLDMAN-PROBE] found "
        f"{len(script_sources)} script(s)",
        file=sys.stderr,
    )

    # Inspect only a limited number of JS assets so the research
    # Action doesn't become excessively expensive.
    for src in script_sources[:15]:
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
                f"[GOLDMAN-PROBE] script fetch failed "
                f"{script_url}: {exc}",
                file=sys.stderr,
            )
            continue

        script = script_response.text

        script_matches: set[str] = set()

        for pattern in patterns:
            for match in re.findall(
                pattern,
                script,
                flags=re.IGNORECASE,
            ):
                script_matches.add(
                    urljoin(
                        script_url,
                        match,
                    )
                )

        if not script_matches:
            continue

        print(
            f"[GOLDMAN-PROBE] script={script_url}",
            file=sys.stderr,
        )

        for match in sorted(script_matches):
            print(
                f"[GOLDMAN-PROBE] "
                f"candidate={match[:500]}",
                file=sys.stderr,
            )


if __name__ == "__main__":
    probe_goldman()