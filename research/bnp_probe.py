import re
import sys
from urllib.parse import urljoin

import requests


_URL = "https://group.bnpparibas/en/careers"
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
            "Accept": "text/html,application/xhtml+xml,*/*",
        },
    )

    if not response.ok:
        print(
            f"[BNP-PROBE] fetch_failed "
            f"url={url} "
            f"status={response.status_code} "
            f"final_url={response.url} "
            f"content_type="
            f"{response.headers.get('Content-Type')} "
            f"server={response.headers.get('Server')}",
            file=sys.stderr,
        )

        print(
            "[BNP-PROBE] body="
            + repr(response.text[:1000]),
            file=sys.stderr,
        )

        response.raise_for_status()

    return response


def _print_matches(
    text: str,
    source: str,
) -> None:
    patterns = {
        "API_URL": (
            r'https?://[^"\'\s<>\\]+(?:api|jobs|careers|search)'
            r'[^"\'\s<>\\]*'
        ),
        "RELATIVE_API": (
            r'["\'](/[^"\']*(?:api|jobs|offers|vacancies|'
            r'positions|search)[^"\']*)["\']'
        ),
    }

    matches: set[tuple[str, str]] = set()

    for label, pattern in patterns.items():
        for match in re.findall(
            pattern,
            text,
            flags=re.IGNORECASE,
        ):
            if isinstance(match, tuple):
                match = match[0]

            matches.add(
                (
                    label,
                    urljoin(source, match),
                )
            )

    for label, match in sorted(matches):
        print(
            f"[BNP-PROBE] {label}={match[:1000]}",
            file=sys.stderr,
        )


def _print_ats_signals(
    text: str,
    source: str,
) -> None:
    providers = (
        "workday",
        "myworkdayjobs",
        "oraclecloud",
        "taleo",
        "successfactors",
        "smartrecruiters",
        "greenhouse",
        "lever",
        "ashby",
        "phenom",
        "eightfold",
        "avature",
        "icims",
    )

    lower = text.lower()

    for provider in providers:
        if provider not in lower:
            continue

        index = lower.find(provider)

        left = max(0, index - 800)
        right = min(
            len(text),
            index + len(provider) + 800,
        )

        context = (
            text[left:right]
            .replace("\n", " ")
        )

        print(
            f"[BNP-PROBE] ATS_SIGNAL={provider} "
            f"source={source}",
            file=sys.stderr,
        )

        print(
            f"[BNP-PROBE] CONTEXT={context}",
            file=sys.stderr,
        )


def probe_bnp() -> None:
    response = _fetch(_URL)

    print(
        f"[BNP-PROBE] final_url={response.url}",
        file=sys.stderr,
    )

    print(
        f"[BNP-PROBE] status={response.status_code}",
        file=sys.stderr,
    )

    print(
        "[BNP-PROBE] content_type="
        f"{response.headers.get('Content-Type')}",
        file=sys.stderr,
    )

    html = response.text

    _print_matches(
        html,
        response.url,
    )

    _print_ats_signals(
        html,
        response.url,
    )

    links = {
        urljoin(response.url, href)
        for href in re.findall(
            r'<a[^>]+href=["\']([^"\']+)["\']',
            html,
            flags=re.IGNORECASE,
        )
    }

    career_links = [
        link
        for link in links
        if any(
            keyword in link.lower()
            for keyword in (
                "job",
                "career",
                "offer",
                "vacan",
                "position",
                "recruit",
                "search",
            )
        )
    ]

    print(
        f"[BNP-PROBE] career_links="
        f"{len(career_links)}",
        file=sys.stderr,
    )

    for link in sorted(career_links)[:30]:
        print(
            f"[BNP-PROBE] CAREER_LINK={link}",
            file=sys.stderr,
        )

    script_sources = {
        urljoin(response.url, src)
        for src in re.findall(
            r'<script[^>]+src=["\']([^"\']+)["\']',
            html,
            flags=re.IGNORECASE,
        )
    }

    print(
        f"[BNP-PROBE] scripts="
        f"{len(script_sources)}",
        file=sys.stderr,
    )

    for script_url in sorted(script_sources)[:30]:
        try:
            script = _fetch(script_url).text
        except requests.RequestException as exc:
            print(
                f"[BNP-PROBE] script_failed="
                f"{script_url}: {exc}",
                file=sys.stderr,
            )
            continue

        interesting = any(
            marker in script.lower()
            for marker in (
                "job",
                "vacan",
                "position",
                "offer",
                "career",
                "workday",
                "oracle",
                "taleo",
                "successfactors",
                "graphql",
                "/api/",
            )
        )

        if not interesting:
            continue

        _print_matches(
            script,
            script_url,
        )

        _print_ats_signals(
            script,
            script_url,
        )


if __name__ == "__main__":
    probe_bnp()