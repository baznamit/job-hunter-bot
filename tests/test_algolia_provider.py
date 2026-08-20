from models.company import (
    Company,
    CompanyCategory,
    Provider,
    ProviderConfig,
    ProviderStatus,
    ProviderType,
)
from src.providers.algolia import (
    AlgoliaAdapter,
)


def _company() -> Company:
    return Company(
        id="msci",
        name="MSCI",
        category=CompanyCategory.FINTECH,
        priority=1,
        career_page="https://careers.msci.com/",
        provider=Provider(
            type=ProviderType.ALGOLIA,
            status=ProviderStatus.PARTIAL,
            config=ProviderConfig(
                app_id="RVMOB42DFH",
                api_key="test-key",
                index_name="test-index",
                base_url=(
                    "https://careers.msci.com"
                ),
                page_size=20,
            ),
        ),
    )


def test_algolia_endpoint():
    adapter = AlgoliaAdapter()

    assert adapter._endpoint(
        _company()
    ) == (
        "https://rvmob42dfh-dsn.algolia.net/"
        "1/indexes/*/queries"
    )


def test_parse_msci_job():
    adapter = AlgoliaAdapter()

    raw = [
        {
            "objectID": (
                "FDF6DC7A9A24BD12E302D021D9"
            ),
            "ats_requisition_id": "2026-5681",
            "title": "Java Developer, CDP API",
            "display_location": "Budapest",
            "country": "Hungary",
            "department": "Data and Operations",
            "description": "Build Java APIs.",
            "jd_url": (
                "/job/data-and-operations/"
                "budapest/"
                "java-developer-cdp-api/"
                "2026-5681"
            ),
        }
    ]

    jobs = adapter.parse(
        raw,
        _company(),
    )

    assert len(jobs) == 1

    job = jobs[0]

    assert job.id == "2026-5681"
    assert job.title == (
        "Java Developer, CDP API"
    )
    assert job.location == "Budapest"
    assert job.department == (
        "Data and Operations"
    )
    assert str(job.url) == (
        "https://careers.msci.com/"
        "job/data-and-operations/"
        "budapest/"
        "java-developer-cdp-api/"
        "2026-5681"
    )


def test_parse_uses_location_fallback():
    adapter = AlgoliaAdapter()

    raw = [
        {
            "objectID": "abc",
            "ats_requisition_id": "2026-1",
            "title": "Software Engineer",
            "location": "Mumbai",
            "jd_url": (
                "/job/technology/mumbai/"
                "software-engineer/2026-1"
            ),
        }
    ]

    jobs = adapter.parse(
        raw,
        _company(),
    )

    assert jobs[0].location == "Mumbai"