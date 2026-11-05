import pytest

from models import Job
from research.new_company_stage4_probe import (
    fingerprint,
    identity_report,
    overlap_report,
    url_job_id,
)


def job(job_id, title, location, url):
    return Job(
        id=job_id,
        title=title,
        location=location,
        company="Wissen",
        url=url,
    )


def test_url_job_id():
    assert url_job_id(
        "https://jobs.wissen.com/job/"
        "Bangalore-Architect/60692344/"
    ) == "60692344"

    assert url_job_id(
        "https://example.com/jobs/60692344"
    ) is None


def test_identity_report_allows_requisition_id_difference():
    jobs = [
        job(
            "110582",
            "Java",
            "Pune",
            "https://example.com/job/"
            "Pune-Java/59593944/",
        )
    ]

    assert len(identity_report(jobs)) == 1


def test_identity_report_rejects_duplicate_url():
    jobs = [
        job(
            "1",
            "Java",
            "Pune",
            "https://example.com/job/Pune-Java/1/",
        ),
        job(
            "2",
            "Java",
            "Pune",
            "https://example.com/job/Pune-Java/1/",
        ),
    ]

    with pytest.raises(
        AssertionError,
        match="seen-store",
    ):
        identity_report(jobs)


def test_cross_source_overlap_is_normalized():
    zoho = [
        job(
            "z1",
            "Java - Developer",
            "Pune, India",
            "https://zoho.example/jobs/1",
        )
    ]

    sf = [
        job(
            "s1",
            "java developer",
            "Pune India",
            "https://sf.example/job/Pune-Java/2/",
        )
    ]

    assert fingerprint(zoho[0]) == fingerprint(sf[0])
    assert len(overlap_report(zoho, sf)) == 1
