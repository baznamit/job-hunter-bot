import json
import re
import sys
from urllib.parse import urljoin

import requests


_TIMEOUT = 30

_TALENTBREW = [
    {
        "name": "Citi",
        "base": "https://jobs.citi.com",
    },
    {
        "name": "BlackRock",
        "base": "https://careers.blackrock.com",
    },
]

_MSCI_BASE = "https://careers.msci.com"

_MSCI_APP_ID = "RVMOB42DFH"
_MSCI_API_KEY = "629e647c6a9a8b542fb1022001313a7e"
_MSCI_INDEX = "production__mscicare2201__sort-rank"


def _headers() -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 "
            "(compatible; JobHunterBot/1.0)"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,"
            "application/json;q=0.9,*/*;q=0.8"
        ),
    }


def _clean(value: str) -> str:
    value = re.sub(
        r"<[^>]+>",
        " ",
        value,
    )

    value = (
        value
        .replace("&amp;", "&")
        .replace("&#39;", "'")
        .replace("&quot;", '"')
    )

    return re.sub(
        r"\s+",
        " ",
        value,
    ).strip()


def _extract_talentbrew_jobs(
    html: str,
    base: str,
) -> list[tuple[str, str]]:
    links = re.findall(
        r'<a\b([^>]+)>(.*?)</a>',
        html,
        flags=(
            re.IGNORECASE
            | re.DOTALL
        ),
    )

    jobs: list[tuple[str, str]] = []
    seen: set[str] = set()

    for attrs, body in links:
        href_match = re.search(
            r'href=["\']([^"\']+)["\']',
            attrs,
            flags=re.IGNORECASE,
        )

        if not href_match:
            continue

        href = href_match.group(1)

        # TalentBrew job detail URLs commonly contain /job/
        # or /job-detail/. Capture both for this probe.
        lower = href.lower()

        if (
            "/job/" not in lower
            and "/job-detail/" not in lower
        ):
            continue

        url = urljoin(
            base,
            href,
        )

        if url in seen:
            continue

        seen.add(url)

        title = _clean(body)

        jobs.append(
            (
                title,
                url,
            )
        )

    return jobs


def probe_talentbrew(
    target: dict,
) -> None:
    name = target["name"]
    base = target["base"]

    page_jobs = []

    for page in (1, 2):
        response = requests.get(
            f"{base}/search-jobs",
            params={
                "p": page,
            },
            headers=_headers(),
            timeout=_TIMEOUT,
            allow_redirects=True,
        )

        print(
            f"[FINAL-PROBE] {name}: "
            f"page={page} "
            f"status={response.status_code} "
            f"url={response.url} "
            f"length={len(response.content)}",
            file=sys.stderr,
        )

        if response.status_code != 200:
            continue

        jobs = _extract_talentbrew_jobs(
            response.text,
            base,
        )

        page_jobs.append(jobs)

        print(
            f"[FINAL-PROBE] {name}: "
            f"page={page} "
            f"job_links={len(jobs)}",
            file=sys.stderr,
        )

        for title, url in jobs[:5]:
            print(
                f"[FINAL-PROBE] {name}: "
                f"JOB title={title!r} "
                f"url={url}",
                file=sys.stderr,
            )

        # Useful structural snippets around the actual results.
        for marker in (
            'id="search-results-list"',
            "search-results-list",
            "TotalPages",
            "TotalResults",
            "data-job-id",
        ):
            index = response.text.find(
                marker
            )

            if index == -1:
                continue

            context = response.text[
                max(0, index - 500):
                index + 2500
            ].replace(
                "\n",
                " ",
            )

            print(
                f"[FINAL-PROBE] {name}: "
                f"CONTEXT marker={marker!r} "
                f"{context[:3000]}",
                file=sys.stderr,
            )

    if len(page_jobs) == 2:
        urls_1 = {
            url
            for _, url in page_jobs[0]
        }

        urls_2 = {
            url
            for _, url in page_jobs[1]
        }

        print(
            f"[FINAL-PROBE] {name}: "
            f"pages_different="
            f"{urls_1 != urls_2} "
            f"overlap={len(urls_1 & urls_2)}",
            file=sys.stderr,
        )

    if page_jobs and page_jobs[0]:
        detail_url = page_jobs[0][0][1]

        response = requests.get(
            detail_url,
            headers=_headers(),
            timeout=_TIMEOUT,
            allow_redirects=True,
        )

        print(
            f"[FINAL-PROBE] {name}: "
            f"detail_status="
            f"{response.status_code} "
            f"detail_url={response.url} "
            f"detail_length="
            f"{len(response.content)}",
            file=sys.stderr,
        )


def probe_msci() -> None:
    endpoint = (
        "https://"
        f"{_MSCI_APP_ID.lower()}-dsn.algolia.net/"
        "1/indexes/*/queries"
    )

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Algolia-Application-Id": (
            _MSCI_APP_ID
        ),
        "X-Algolia-API-Key": (
            _MSCI_API_KEY
        ),
        "User-Agent": (
            "Mozilla/5.0 "
            "(compatible; JobHunterBot/1.0)"
        ),
    }

    payload = {
        "requests": [
            {
                "indexName": _MSCI_INDEX,
                "params": (
                    "query="
                    "&hitsPerPage=20"
                    "&page=0"
                ),
            },
            {
                "indexName": _MSCI_INDEX,
                "params": (
                    "query="
                    "&hitsPerPage=20"
                    "&page=1"
                ),
            },
        ]
    }

    try:
        response = requests.post(
            endpoint,
            headers=headers,
            json=payload,
            timeout=_TIMEOUT,
        )

    except requests.RequestException as exc:
        print(
            "[FINAL-PROBE] MSCI: "
            f"FAILED {type(exc).__name__}: "
            f"{exc}",
            file=sys.stderr,
        )
        return

    print(
        "[FINAL-PROBE] MSCI: "
        f"status={response.status_code} "
        f"content_type="
        f"{response.headers.get('Content-Type')} "
        f"length={len(response.content)}",
        file=sys.stderr,
    )

    if response.status_code != 200:
        print(
            "[FINAL-PROBE] MSCI: "
            f"body={response.text[:2000]!r}",
            file=sys.stderr,
        )
        return

    data = response.json()

    results = data.get(
        "results",
        [],
    )

    print(
        "[FINAL-PROBE] MSCI: "
        f"result_sets={len(results)}",
        file=sys.stderr,
    )

    page_hits = []

    for index, result in enumerate(
        results
    ):
        hits = result.get(
            "hits",
            [],
        )

        page_hits.append(hits)

        print(
            "[FINAL-PROBE] MSCI: "
            f"page={index} "
            f"nbHits={result.get('nbHits')} "
            f"nbPages={result.get('nbPages')} "
            f"returned={len(hits)}",
            file=sys.stderr,
        )

        for hit in hits[:3]:
            print(
                "[FINAL-PROBE] MSCI: "
                "HIT="
                + json.dumps(
                    hit,
                    ensure_ascii=False,
                )[:5000],
                file=sys.stderr,
            )

    if len(page_hits) == 2:
        ids_1 = {
            hit.get("objectID")
            for hit in page_hits[0]
        }

        ids_2 = {
            hit.get("objectID")
            for hit in page_hits[1]
        }

        print(
            "[FINAL-PROBE] MSCI: "
            f"pages_different="
            f"{ids_1 != ids_2} "
            f"overlap={len(ids_1 & ids_2)}",
            file=sys.stderr,
        )


def main() -> None:
    for target in _TALENTBREW:
        probe_talentbrew(
            target
        )

    probe_msci()


if __name__ == "__main__":
    main()