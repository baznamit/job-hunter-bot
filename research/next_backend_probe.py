import json
import re
import sys
from urllib.parse import urljoin

import requests


_TIMEOUT = 30

_TARGETS = [
    {
        "name": "Citi",
        "url": "https://jobs.citi.com/search-jobs",
    },
    {
        "name": "BlackRock",
        "url": "https://careers.blackrock.com/search-jobs",
    },
    {
        "name": "MSCI",
        "url": "https://careers.msci.com/",
    },
]


def _fetch(url: str) -> requests.Response:
    return requests.get(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/127.0.0.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,"
                "application/xml;q=0.9,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        },
        timeout=_TIMEOUT,
        allow_redirects=True,
    )


def _interesting_urls(
    text: str,
    base_url: str,
) -> set[str]:
    results: set[str] = set()

    # Absolute URLs.
    for value in re.findall(
        r'https?://[^"\'\s<>\\]+',
        text,
        flags=re.IGNORECASE,
    ):
        lower = value.lower()

        if any(
            marker in lower
            for marker in (
                "/api/",
                "graphql",
                "search",
                "jobs",
                "careers",
                "eightfold",
                "phenom",
                "avature",
                "workday",
                "icims",
            )
        ):
            results.add(
                html_unescape(value)
            )

    # Interesting relative URLs.
    for value in re.findall(
        r'["\']([^"\']+)["\']',
        text,
    ):
        lower = value.lower()

        if any(
            marker in lower
            for marker in (
                "/api/",
                "/search",
                "graphql",
                "/jobs",
                "jobsearch",
            )
        ):
            if len(value) <= 1000:
                results.add(
                    urljoin(
                        base_url,
                        html_unescape(value),
                    )
                )

    return results


def html_unescape(value: str) -> str:
    return (
        value
        .replace("&amp;", "&")
        .replace("\\u0026", "&")
        .replace("\\/", "/")
    )


def _print_context(
    name: str,
    source: str,
    text: str,
    needle: str,
    max_matches: int = 3,
) -> None:
    lower = text.lower()
    target = needle.lower()

    start = 0
    found = 0

    while found < max_matches:
        index = lower.find(
            target,
            start,
        )

        if index == -1:
            break

        left = max(
            0,
            index - 700,
        )
        right = min(
            len(text),
            index + len(needle) + 1200,
        )

        context = (
            text[left:right]
            .replace("\n", " ")
        )

        print(
            f"[BACKEND-PROBE] {name}: "
            f"CONTEXT source={source} "
            f"needle={needle!r}",
            file=sys.stderr,
        )

        print(
            f"[BACKEND-PROBE] {name}: "
            f"{context[:2500]}",
            file=sys.stderr,
        )

        found += 1
        start = index + len(needle)


def _inspect_text(
    name: str,
    source: str,
    text: str,
) -> None:
    urls = _interesting_urls(
        text,
        source,
    )

    for url in sorted(urls):
        print(
            f"[BACKEND-PROBE] {name}: "
            f"CANDIDATE_URL={url[:1200]}",
            file=sys.stderr,
        )

    needles = (
        "fetch(",
        "axios",
        "XMLHttpRequest",
        "/api/",
        "graphql",
        "search-jobs",
        "job-search",
        "jobSearch",
        "searchJobs",
        "eightfold",
        "phenom",
        "avature",
        "workday",
        "icims",
    )

    for needle in needles:
        if needle.lower() in text.lower():
            _print_context(
                name,
                source,
                text,
                needle,
            )


def _inspect_embedded_json(
    name: str,
    html: str,
) -> None:
    patterns = (
        (
            "NEXT_DATA",
            r'<script[^>]+id=["\']__NEXT_DATA__["\']'
            r'[^>]*>(.*?)</script>',
        ),
        (
            "APPLICATION_JSON",
            r'<script[^>]+type=["\']application/json["\']'
            r'[^>]*>(.*?)</script>',
        ),
    )

    for label, pattern in patterns:
        matches = re.findall(
            pattern,
            html,
            flags=(
                re.IGNORECASE
                | re.DOTALL
            ),
        )

        for index, raw in enumerate(
            matches[:5]
        ):
            raw = raw.strip()

            try:
                parsed = json.loads(raw)

                serialized = json.dumps(
                    parsed,
                    ensure_ascii=False,
                )

            except json.JSONDecodeError:
                serialized = raw

            print(
                f"[BACKEND-PROBE] {name}: "
                f"{label}[{index}]="
                f"{serialized[:5000]}",
                file=sys.stderr,
            )


def probe(target: dict) -> None:
    name = target["name"]
    url = target["url"]

    print(
        f"[BACKEND-PROBE] {name}: "
        f"START url={url}",
        file=sys.stderr,
    )

    try:
        response = _fetch(url)
    except requests.RequestException as exc:
        print(
            f"[BACKEND-PROBE] {name}: "
            f"FETCH_FAILED "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return

    print(
        f"[BACKEND-PROBE] {name}: "
        f"status={response.status_code} "
        f"final_url={response.url} "
        f"content_type="
        f"{response.headers.get('Content-Type')} "
        f"body_length={len(response.content)}",
        file=sys.stderr,
    )

    if response.status_code != 200:
        print(
            f"[BACKEND-PROBE] {name}: "
            f"body={response.text[:1000]!r}",
            file=sys.stderr,
        )
        return

    html = response.text

    _inspect_embedded_json(
        name,
        html,
    )

    _inspect_text(
        name,
        response.url,
        html,
    )

    scripts = re.findall(
        r'<script[^>]+src=["\']([^"\']+)["\']',
        html,
        flags=re.IGNORECASE,
    )

    script_urls = []

    for src in scripts:
        script_url = urljoin(
            response.url,
            html_unescape(src),
        )

        if script_url not in script_urls:
            script_urls.append(script_url)

    print(
        f"[BACKEND-PROBE] {name}: "
        f"scripts={len(script_urls)}",
        file=sys.stderr,
    )

    # Avoid turning the research run into hundreds of requests.
    for script_url in script_urls[:30]:
        try:
            script_response = _fetch(
                script_url
            )
        except requests.RequestException:
            continue

        if script_response.status_code != 200:
            continue

        script = script_response.text
        lower = script.lower()

        interesting = any(
            marker in lower
            for marker in (
                "/api/",
                "graphql",
                "search-jobs",
                "jobsearch",
                "searchjobs",
                "eightfold",
                "phenom",
                "avature",
                "workday",
                "icims",
            )
        )

        if not interesting:
            continue

        print(
            f"[BACKEND-PROBE] {name}: "
            f"INTERESTING_SCRIPT="
            f"{script_url}",
            file=sys.stderr,
        )

        _inspect_text(
            name,
            script_url,
            script,
        )


def main() -> None:
    for target in _TARGETS:
        probe(target)


if __name__ == "__main__":
    main()