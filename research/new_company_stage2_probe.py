"""
Second-stage probe for existing provider compatibility.

Run:
    python -u -m research.new_company_stage2_probe
"""

import re
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from src.providers.successfactors import SuccessFactorsAdapter

TIMEOUT = 20

TARGETS = {
    "DELOITTE-P0": (
        "https://southasiacareers.deloitte.com/"
        "go/Deloitte-India/718244/?q=&title=Java"
    ),
    "DELOITTE-P25": (
        "https://southasiacareers.deloitte.com/"
        "go/Deloitte-India/718244/25/?q=&title=Java"
    ),
    "DELOITTE-P50": (
        "https://southasiacareers.deloitte.com/"
        "go/Deloitte-India/718244/50/?q=&title=Java"
    ),
    "WISSEN-SF-JAVA": (
        "https://jobs.wissen.com/search/?q=Java"
    ),
    "WISSEN-SF-ALL": (
        "https://jobs.wissen.com/search/"
    ),
}


def probe(name, url):
    response = requests.get(
        url,
        timeout=TIMEOUT,
        headers={
            "User-Agent": "JobHunterResearch/1.0",
            "Accept": "text/html",
        },
    )

    print(
        f"\n[{name}] status={response.status_code} "
        f"bytes={len(response.content)} "
        f"final={response.url}"
    )

    response.raise_for_status()

    if "html" not in response.headers.get(
        "Content-Type", ""
    ).lower():
        raise RuntimeError("Unexpected content type")

    soup = BeautifulSoup(response.text, "html.parser")

    if name.startswith("DELOITTE") or name.startswith("WISSEN-SF"):
        print(f"\n[{name}] JOB LINK STRUCTURE")

        for anchor in soup.select('a[href*="/job/"]')[:35]:
            href = anchor.get("href", "")

            ancestors = [
                {
                    "tag": parent.name,
                    "id": parent.get("id"),
                    "class": parent.get("class"),
                }
                for parent in list(anchor.parents)[:5]
            ]

            print(
                f"[{name}] "
                f"href={href!r} "
                f"text={anchor.get_text(' ', strip=True)[:100]!r} "
                f"parents={ancestors}"
            )

    adapter = SuccessFactorsAdapter()

    urls = adapter._extract_job_urls(
        response.text,
        response.url,
    )

    ids = {}
    for job_url in urls:
        parsed = urlparse(job_url)

        match = re.search(
            r"/job/[^/]+/(\d+)/?$",
            parsed.path,
            re.IGNORECASE,
        )

        if match:
            ids[match.group(1)] = job_url

    print(
        f"[{name}] adapter_urls={len(urls)} "
        f"numeric_job_ids={len(ids)}"
    )

    for job_id, job_url in list(ids.items())[:5]:
        print(f"[{name}] JOB {job_id} {job_url}")

    print(
        f"[{name}] pagination_links="
        f"{len(soup.select('a[href*=\"/25/\"], a[href*=\"/50/\"]'))}"
    )

    return set(ids)


def main():
    results = {}

    for name, url in TARGETS.items():
        try:
            results[name] = probe(name, url)
        except requests.RequestException as exc:
            print(f"[{name}] REQUEST_ERROR {exc}")
        except Exception as exc:
            print(f"[{name}] ERROR {type(exc).__name__}: {exc}")

    for left, right in (
        ("DELOITTE-P0", "DELOITTE-P25"),
        ("DELOITTE-P25", "DELOITTE-P50"),
        ("WISSEN-SF-JAVA", "WISSEN-SF-ALL"),
    ):
        if left in results and right in results:
            a, b = results[left], results[right]
            print(
                f"[COMPARE] {left}/{right} "
                f"overlap={len(a & b)} "
                f"left={len(a)} right={len(b)}"
            )

    print("[STAGE2] Finished")


if __name__ == "__main__":
    main()
