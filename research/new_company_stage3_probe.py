"""
Stage-3 production-style validation for Deloitte India
and Wissen SuccessFactors.

Run:
    python -u -m research.new_company_stage3_probe
"""

import re
import time
from collections import Counter
from urllib.parse import urlparse

from research.loader import load_registry
from src.providers.successfactors import SuccessFactorsAdapter

COMPANY_IDS = (
    "deloitte_india",
    "wissen_successfactors",
)

JOB_ID_PATTERN = re.compile(
    r"/job/[^/]+/(\d+)/?$",
    re.IGNORECASE,
)


def validate_company(company):
    adapter = SuccessFactorsAdapter()
    config = company.provider.config

    print(f"\n{'=' * 70}")
    print(f"[STAGE3] Company: {company.name}")
    print(f"[STAGE3] ID: {company.id}")
    print(f"[STAGE3] Enabled: {company.enabled}")
    print(f"{'=' * 70}")

    if not company.enabled:
        raise AssertionError(
            f"{company.id}: must be enabled"
        )

    if not config.job_link_selector:
        raise AssertionError(
            f"{company.id}: missing job_link_selector"
        )

    # Verify the first listing page with the actual
    # configured selector.
    listing_url = adapter._listing_url(
        company,
        offset=0,
    )

    listing_html = adapter._fetch_html(
        listing_url,
        company,
    )

    scoped_urls = adapter._extract_job_urls(
        listing_html,
        config.base_url,
        config.job_link_selector,
    )

    unscoped_urls = adapter._extract_job_urls(
        listing_html,
        config.base_url,
    )

    print(f"[STAGE3] listing_url={listing_url}")
    print(
        f"[STAGE3] first_page_unscoped="
        f"{len(unscoped_urls)}"
    )
    print(
        f"[STAGE3] first_page_scoped="
        f"{len(scoped_urls)}"
    )

    if not scoped_urls:
        raise AssertionError(
            f"{company.id}: selector returned zero jobs"
        )

    if company.id == "deloitte_india":
        if len(scoped_urls) != 25:
            raise AssertionError(
                "Deloitte: expected 25 scoped jobs "
                f"on first page, got {len(scoped_urls)}"
            )

        if any(
            "/job/Returnship/" in url
            for url in scoped_urls
        ):
            raise AssertionError(
                "Deloitte: Returnship link was included"
            )

    # Exercise the real adapter, including pagination,
    # detail fetching and normalization.
    started = time.perf_counter()

    raw_urls = adapter._fetch_raw(company)

    fetch_raw_seconds = (
        time.perf_counter() - started
    )

    print(
        f"[STAGE3] raw_urls={len(raw_urls)}"
    )
    print(
        f"[STAGE3] fetch_raw_seconds="
        f"{fetch_raw_seconds:.2f}"
    )

    if not raw_urls:
        raise AssertionError(
            f"{company.id}: no raw job URLs"
        )

    if len(raw_urls) != len(set(raw_urls)):
        raise AssertionError(
            f"{company.id}: duplicate raw URLs"
        )

    started = time.perf_counter()

    jobs = adapter.fetch_jobs(company)

    fetch_jobs_seconds = (
        time.perf_counter() - started
    )

    print(
        f"[STAGE3] normalized_jobs={len(jobs)}"
    )
    print(
        f"[STAGE3] fetch_jobs_seconds="
        f"{fetch_jobs_seconds:.2f}"
    )

    if not jobs:
        raise AssertionError(
            f"{company.id}: no normalized jobs"
        )

    if len(jobs) != len(raw_urls):
        raise AssertionError(
            f"{company.id}: normalization incomplete "
            f"raw={len(raw_urls)} "
            f"normalized={len(jobs)}"
        )

    ids = [job.id for job in jobs]
    urls = [str(job.url) for job in jobs]

    duplicate_ids = [
        job_id
        for job_id, count in Counter(ids).items()
        if count > 1
    ]

    if duplicate_ids:
        raise AssertionError(
            f"{company.id}: duplicate job IDs "
            f"{duplicate_ids[:5]}"
        )

    if len(urls) != len(set(urls)):
        raise AssertionError(
            f"{company.id}: duplicate normalized URLs"
        )

    expected_host = urlparse(
        config.base_url
    ).hostname

    for job in jobs:
        if not job.id or not job.title.strip():
            raise AssertionError(
                f"{company.id}: invalid job metadata"
            )

        if not job.location.strip():
            raise AssertionError(
                f"{company.id}: empty location"
            )

        parsed = urlparse(str(job.url))

        if parsed.hostname != expected_host:
            raise AssertionError(
                f"{company.id}: unexpected job host "
                f"{parsed.hostname}"
            )

        match = JOB_ID_PATTERN.search(parsed.path)

        if not match:
            raise AssertionError(
                f"{company.id}: invalid job URL "
                f"{job.url}"
            )

    print(
        f"[STAGE3] unique_ids={len(set(ids))}"
    )
    print(
        f"[STAGE3] unique_urls={len(set(urls))}"
    )

    for job in jobs[:5]:
        print(
            f"[STAGE3] SAMPLE "
            f"id={job.id!r} "
            f"title={job.title!r} "
            f"location={job.location!r} "
            f"url={job.url}"
        )

    print(
        f"[STAGE3] {company.id}: PASSED"
    )


def main():
    registry = load_registry()

    companies = {
        company.id: company
        for company in registry.companies
    }

    failures = []

    for company_id in COMPANY_IDS:
        company = companies.get(company_id)

        if company is None:
            failures.append(
                f"{company_id}: missing registry entry"
            )
            continue

        try:
            validate_company(company)

        except Exception as exc:
            failures.append(
                f"{company_id}: "
                f"{type(exc).__name__}: {exc}"
            )

            print(
                f"[STAGE3] {company_id}: "
                f"FAILED: {exc}"
            )

    print(f"\n{'=' * 70}")
    print("[STAGE3] FINAL SUMMARY")
    print(f"{'=' * 70}")

    if failures:
        for failure in failures:
            print(f"[STAGE3] ERROR {failure}")

        raise SystemExit(1)

    print("[STAGE3] ALL COMPANIES PASSED")


if __name__ == "__main__":
    main()
