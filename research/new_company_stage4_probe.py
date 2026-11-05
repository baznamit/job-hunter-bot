"""Read-only pre-activation identity and cross-source overlap probe."""

import re
from urllib.parse import urlparse

from research.loader import load_registry
from src.providers.successfactors import SuccessFactorsAdapter
from src.providers.zoho_recruit import ZohoRecruitAdapter
from src.store import SeenStore


def url_job_id(url: str) -> str | None:
    match = re.search(
        r"/job/[^/]+/(\d+)/?$",
        urlparse(url).path,
        re.I,
    )
    return match.group(1) if match else None


def fingerprint(job) -> tuple[str, str]:
    title = re.sub(
        r"[^a-z0-9]+",
        " ",
        job.title.casefold(),
    ).strip()

    location = re.sub(
        r"[^a-z0-9]+",
        " ",
        job.location.casefold(),
    ).strip()

    return title, location


def identity_report(jobs):
    differences = [
        (
            job.id,
            url_job_id(str(job.url)),
            str(job.url),
        )
        for job in jobs
        if url_job_id(str(job.url)) != job.id
    ]

    keys = [
        SeenStore._key(job)
        for job in jobs
    ]

    if len(keys) != len(set(keys)):
        raise AssertionError(
            "Duplicate seen-store URL keys"
        )

    if len({job.id for job in jobs}) != len(jobs):
        raise AssertionError(
            "Duplicate normalized job IDs"
        )

    return differences


def overlap_report(left, right):
    left_by_fingerprint = {}

    for job in left:
        left_by_fingerprint.setdefault(
            fingerprint(job), []
        ).append(job)

    return [
        (left_job, right_job)
        for right_job in right
        for left_job in left_by_fingerprint.get(
            fingerprint(right_job), []
        )
    ]


def main():
    companies = {
        company.id: company
        for company in load_registry().companies
    }

    for company_id in (
        "deloitte_india",
        "wissen_successfactors",
    ):
        assert companies[company_id].enabled, (
            f"{company_id} must be enabled"
        )

    assert companies["wissen"].enabled

    sf = SuccessFactorsAdapter()

    deloitte = sf.fetch_jobs(
        companies["deloitte_india"]
    )

    wissen_sf = sf.fetch_jobs(
        companies["wissen_successfactors"]
    )

    wissen_zoho = ZohoRecruitAdapter().fetch_jobs(
        companies["wissen"]
    )

    for name, jobs in (
        ("deloitte", deloitte),
        ("wissen_sf", wissen_sf),
        ("wissen_zoho", wissen_zoho),
    ):
        print(
            f"[STAGE4] {name}: jobs={len(jobs)}"
        )

        if not jobs:
            raise AssertionError(
                f"{name}: zero jobs; cannot validate"
            )

        differences = identity_report(jobs)

        print(
            f"[STAGE4] {name}: "
            f"normalized_vs_url_id_differences="
            f"{len(differences)}"
        )

        for normalized_id, url_id, url in differences[:10]:
            print(
                f"[STAGE4] ID_DIFF "
                f"normalized={normalized_id!r} "
                f"url_id={url_id!r} "
                f"url={url}"
            )

    overlaps = overlap_report(
        wissen_zoho,
        wissen_sf,
    )

    zoho_urls = {
        SeenStore._key(job)
        for job in wissen_zoho
    }

    sf_urls = {
        SeenStore._key(job)
        for job in wissen_sf
    }

    print(
        "[STAGE4] wissen_exact_url_overlap="
        f"{len(zoho_urls & sf_urls)}"
    )

    print(
        "[STAGE4] wissen_exact_title_location_overlap="
        f"{len(overlaps)}"
    )

    for zoho_job, sf_job in overlaps[:15]:
        print(
            f"[STAGE4] POSSIBLE_OVERLAP "
            f"zoho={zoho_job.url} "
            f"sf={sf_job.url} "
            f"title={sf_job.title!r}"
        )

    print(
        "[STAGE4] READ-ONLY COMPLETE "
        "(possible overlaps require manual review)"
    )


if __name__ == "__main__":
    main()
