import re
import sys
from urllib.parse import urljoin

import requests


_URL = (
    "https://bwelcome.hr.bnpparibas/"
    "en_US/externalcareers/"
)

_TIMEOUT = 30


def probe_bnp() -> None:
    response = requests.get(
        _URL,
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

    print(
        f"[BNP-PROBE] status={response.status_code}",
        file=sys.stderr,
    )

    print(
        f"[BNP-PROBE] final_url={response.url}",
        file=sys.stderr,
    )

    print(
        "[BNP-PROBE] content_type="
        f"{response.headers.get('Content-Type')}",
        file=sys.stderr,
    )

    print(
        f"[BNP-PROBE] body_length="
        f"{len(response.content)}",
        file=sys.stderr,
    )

    html = response.text

    # ---------------------------------------------------------
    # Extract links
    # ---------------------------------------------------------

    hrefs = re.findall(
        r'href=["\']([^"\']+)["\']',
        html,
        flags=re.IGNORECASE,
    )

    links = {
        urljoin(response.url, href)
        for href in hrefs
    }

    interesting_links = [
        link
        for link in links
        if any(
            word in link.lower()
            for word in (
                "job",
                "career",
                "search",
                "position",
                "vacan",
                "detail",
            )
        )
    ]

    print(
        "[BNP-PROBE] "
        f"interesting_links={len(interesting_links)}",
        file=sys.stderr,
    )

    for link in sorted(interesting_links)[:50]:
        print(
            f"[BNP-PROBE] LINK={link}",
            file=sys.stderr,
        )

    # ---------------------------------------------------------
    # Extract forms
    # ---------------------------------------------------------

    forms = re.findall(
        r'<form\b[^>]*>',
        html,
        flags=re.IGNORECASE,
    )

    print(
        f"[BNP-PROBE] forms={len(forms)}",
        file=sys.stderr,
    )

    for form in forms[:20]:
        print(
            "[BNP-PROBE] FORM="
            + form[:1000],
            file=sys.stderr,
        )

    # ---------------------------------------------------------
    # Look specifically for Avature routes
    # ---------------------------------------------------------

    route_patterns = (
        r'["\']([^"\']*SearchJobs[^"\']*)["\']',
        r'["\']([^"\']*JobDetail[^"\']*)["\']',
        r'["\']([^"\']*JobDetails[^"\']*)["\']',
        r'["\']([^"\']*Search[^"\']*Job[^"\']*)["\']',
    )

    routes: set[str] = set()

    for pattern in route_patterns:
        for match in re.findall(
            pattern,
            html,
            flags=re.IGNORECASE,
        ):
            routes.add(
                urljoin(
                    response.url,
                    match,
                )
            )

    print(
        f"[BNP-PROBE] routes={len(routes)}",
        file=sys.stderr,
    )

    for route in sorted(routes):
        print(
            f"[BNP-PROBE] ROUTE={route[:1000]}",
            file=sys.stderr,
        )

    # ---------------------------------------------------------
    # Search useful words with context
    # ---------------------------------------------------------

    for needle in (
        "SearchJobs",
        "JobDetail",
        "JobDetails",
        "jobId",
        "jobOffset",
        "externalcareers",
    ):
        lower = html.lower()
        index = lower.find(
            needle.lower()
        )

        if index == -1:
            continue

        left = max(
            0,
            index - 1000,
        )

        right = min(
            len(html),
            index + len(needle) + 2000,
        )

        context = (
            html[left:right]
            .replace("\n", " ")
        )

        print(
            f"[BNP-PROBE] CONTEXT={needle}",
            file=sys.stderr,
        )

        print(
            f"[BNP-PROBE] {context}",
            file=sys.stderr,
        )


if __name__ == "__main__":
    probe_bnp()