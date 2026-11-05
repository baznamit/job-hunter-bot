"""Read-only S&P Global Stage-2 ATS diagnostic."""

import json
import re
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from research.loader import load_registry
from src.providers.workday import WorkdayAdapter

LISTING = "https://careers.spglobal.com/jobs"
DETAIL = "https://careers.spglobal.com/jobs/324329?lang=en-us"
TIMEOUT = 20

ROLE_RE = re.compile(
    r"java|spring|backend|back.end|full.stack|"
    r"software engineer|developer|microservices",
    re.I,
)

INDIA_RE = re.compile(
    r"india|mumbai|navi mumbai|bengaluru|bangalore|"
    r"hyderabad|chennai|pune|noida|gurgaon|gurugram",
    re.I,
)

URL_RE = re.compile(
    r"""(?:"|')([^"']*(?:/api/|/jobs|search)[^"']*)(?:"|')""",
    re.I,
)


def unique_values(values):
    return list(dict.fromkeys(values))


def inspect_workday(company):
    adapter = WorkdayAdapter()
    started = time.perf_counter()

    raw = adapter._fetch_raw(company)
    postings = raw.get("jobPostings", [])
    jobs = adapter.parse(raw, company)

    elapsed = time.perf_counter() - started

    paths = [
        str(item.get("externalPath", ""))
        for item in postings
    ]

    ids = [str(job.id) for job in jobs]
    urls = [str(job.url) for job in jobs]

    india = [
        job for job in jobs
        if INDIA_RE.search(job.location)
    ]

    relevant = [
        job for job in india
        if ROLE_RE.search(job.title)
    ]

    print(f"[SPGLOBAL2] workday_raw={len(postings)}")
    print(f"[SPGLOBAL2] workday_normalized={len(jobs)}")
    print(f"[SPGLOBAL2] workday_unique_paths={len(set(paths))}")
    print(f"[SPGLOBAL2] workday_unique_ids={len(set(ids))}")
    print(f"[SPGLOBAL2] workday_unique_urls={len(set(urls))}")
    print(f"[SPGLOBAL2] workday_india={len(india)}")
    print(f"[SPGLOBAL2] workday_india_relevant={len(relevant)}")
    print(f"[SPGLOBAL2] workday_seconds={elapsed:.2f}")

    if not postings:
        raise AssertionError("Workday returned no postings")

    if len(jobs) != len(postings):
        raise AssertionError(
            "Workday normalization lost records"
        )

    if len(set(paths)) != len(postings):
        raise AssertionError(
            "Duplicate Workday externalPath values"
        )

    if len(set(ids)) != len(jobs):
        raise AssertionError("Duplicate normalized IDs")

    if len(set(urls)) != len(jobs):
        raise AssertionError("Duplicate normalized URLs")

    for job in relevant[:15]:
        print(
            "[SPGLOBAL2] RELEVANT "
            f"id={job.id!r} "
            f"title={job.title!r} "
            f"location={job.location!r} "
            f"url={job.url}"
        )

    return jobs


def extract_jsonld(soup):
    objects = []

    for script in soup.select(
        'script[type="application/ld+json"]'
    ):
        try:
            data = json.loads(script.get_text())
        except (ValueError, TypeError):
            continue

        candidates = data if isinstance(data, list) else [data]

        for item in candidates:
            if isinstance(item, dict):
                objects.append(item)

    return objects


def inspect_jibe_page(label, url):
    response = requests.get(
        url,
        timeout=TIMEOUT,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/html",
        },
    )

    print(
        f"[SPGLOBAL2] {label}_status={response.status_code} "
        f"final={response.url} "
        f"bytes={len(response.content)}"
    )

    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    print(
        f"[SPGLOBAL2] {label}_title="
        f"{soup.title.get_text(' ', strip=True) if soup.title else ''!r}"
    )

    for item in extract_jsonld(soup):
        print(
            f"[SPGLOBAL2] {label}_jsonld="
            f"{item.get('@type')!r}"
        )

        if item.get("@type") == "JobPosting":
            print(
                f"[SPGLOBAL2] jobposting_title="
                f"{item.get('title')!r}"
            )
            print(
                f"[SPGLOBAL2] jobposting_url="
                f"{item.get('url')!r}"
            )

    scripts = unique_values(
        urljoin(response.url, tag["src"])
        for tag in soup.select("script[src]")
    )

    print(f"[SPGLOBAL2] {label}_scripts={len(scripts)}")

    for script in scripts:
        if "jibe" in script.lower():
            print(f"[SPGLOBAL2] JIBE_ASSET {script}")

    # Extract candidate references from the HTML only.
    # These are leads, not verified API endpoints.
    candidates = unique_values(
        match.group(1)
        for match in URL_RE.finditer(response.text)
    )

    print(
        f"[SPGLOBAL2] {label}_candidate_references="
        f"{len(candidates)}"
    )

    for candidate in candidates[:20]:
        print(
            f"[SPGLOBAL2] CANDIDATE_REFERENCE "
            f"{candidate[:250]}"
        )

    # Print selected page metadata without dumping HTML.
    for tag in soup.select("meta[name], meta[property]"):
        name = tag.get("name") or tag.get("property") or ""

        if any(
            word in name.lower()
            for word in ("description", "application", "site")
        ):
            print(
                f"[SPGLOBAL2] META "
                f"name={name!r} "
                f"content={tag.get('content', '')[:180]!r}"
            )

    return soup


def main():
    companies = {
        company.id: company
        for company in load_registry().companies
    }

    company = companies["spglobal"]

    assert company.enabled
    assert company.provider.type.value == "workday"

    print(
        "[SPGLOBAL2] Starting read-only "
        "S&P Global validation"
    )

    inspect_workday(company)

    for label, url in (
        ("listing", LISTING),
        ("detail", DETAIL),
    ):
        try:
            inspect_jibe_page(label, url)
        except requests.RequestException as exc:
            print(
                f"[SPGLOBAL2] {label}_ERROR="
                f"{type(exc).__name__}: {exc}"
            )

    print(
        "[SPGLOBAL2] COMPLETE "
        "- no Telegram or state writes"
    )


if __name__ == "__main__":
    main()
