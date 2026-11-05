from unittest.mock import patch

import pytest

from models.company import (
    Company,
    CompanyCategory,
    Provider,
    ProviderConfig,
    ProviderStatus,
    ProviderType,
)
from src.providers.atlassian import AtlassianAdapter


def company(detail_limit=None):
    return Company(
        id="atlassian",
        name="Atlassian",
        category=CompanyCategory.DEVELOPER_TOOLS,
        priority=1,
        enabled=False,
        career_page="https://www.atlassian.com/company/careers",
        provider=Provider(
            type=ProviderType.ATLASSIAN,
            status=ProviderStatus.PARTIAL,
            config=ProviderConfig(
                base_url=(
                    "https://www.atlassian.com/"
                    "company/careers/all-jobs"
                ),
                detail_limit=detail_limit,
            ),
        ),
    )


LISTING = """
<a href="/company/careers/details/27346">
Software Engineer II
</a>
<a href="/company/careers/details/25540">
Backend Software Engineer, II
</a>
<a href="/company/careers/details/27346">
Software Engineer II
</a>
"""

DETAIL = """
<main id="content">
  <div>
    <h1>Software Engineer II</h1>
    <span>
      Engineering | Bengaluru, India | Remote, Remote
    </span>
    <a href="https://careers-apac-atlassian.icims.com/jobs/27346/software-engineer-ii/job?mode=apply">
      Apply for this job
    </a>
  </div>
  <section>
    <h2>Your background</h2>
    <p>4+ years of backend engineering experience.</p>
  </section>
</main>
"""


def test_listing_extracts_unique_numeric_ids():
    items = AtlassianAdapter._listing_items(LISTING)

    assert len(items) == 2
    assert [item["id"] for item in items] == [
        "27346",
        "25540",
    ]


def test_detail_extracts_metadata():
    metadata = AtlassianAdapter._detail_metadata(
        DETAIL,
        "Software Engineer II",
    )

    assert metadata["title"] == "Software Engineer II"
    assert "Bengaluru" in metadata["location"]
    assert "Remote" in metadata["location"]
    assert "icims.com" in metadata["apply_url"]
    assert "4+ years" in metadata["description"]


def test_missing_header_fails_visibly():
    with pytest.raises(ValueError):
        AtlassianAdapter._detail_metadata(
            "<main id='content'><h1>Java</h1></main>",
            "Java",
        )


@patch.object(AtlassianAdapter, "_get_html")
def test_fetch_jobs_normalizes(mock_get_html):
    mock_get_html.side_effect = [
        LISTING,
        DETAIL,
    ]

    jobs = AtlassianAdapter().fetch_jobs(
        company(detail_limit=1)
    )

    assert len(jobs) == 1
    assert jobs[0].id == "27346"
    assert jobs[0].title == "Software Engineer II"
    assert jobs[0].company == "Atlassian"
    assert jobs[0].remote is True
    assert str(jobs[0].url) == (
        "https://www.atlassian.com/"
        "company/careers/details/27346"
    )


def test_registry_atlassian_is_disabled():
    from research.loader import load_registry

    entries = [
        c for c in load_registry().companies
        if c.id == "atlassian"
    ]

    assert len(entries) == 1
    assert entries[0].enabled is False
    assert entries[0].provider.type == ProviderType.ATLASSIAN
    assert entries[0].provider.config.detail_limit == 20
