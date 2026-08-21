from models.company import (
    Company,
    CompanyCategory,
    Provider,
    ProviderConfig,
    ProviderStatus,
    ProviderType,
)
from src.providers.bankofamerica import (
    BankOfAmericaAdapter,
)


def _company() -> Company:
    return Company(
        id="bank-of-america",
        name="Bank of America",
        category=CompanyCategory.BANKING,
        priority=1,
        career_page=(
            "https://careers.bankofamerica.com/"
            "en-us/job-search/india"
        ),
        provider=Provider(
            type=ProviderType.BANKOFAMERICA,
            status=ProviderStatus.PARTIAL,
            config=ProviderConfig(
                base_url=(
                    "https://careers.bankofamerica.com"
                ),
                search_terms=[
                    "software engineer",
                ],
            ),
        ),
    )


def test_search_url():
    adapter = BankOfAmericaAdapter()

    assert adapter._search_url(
        _company(),
        "Software Engineer",
    ) == (
        "https://careers.bankofamerica.com/"
        "en-us/job-search/india/"
        "q-software-engineer"
    )


def test_extracts_job():
    adapter = BankOfAmericaAdapter()

    page_html = """
    <div class="job-search-tile">
        <div class="job-search-tile__body">
            <h3 class="job-search-tile__title">
                <a
                    class="job-search-tile__url"
                    href="/en-us/job-detail/26011393/software-engineer-iii-gbs-ind-multiple-locations"
                >
                    Software Engineer III - GBS IND
                </a>
            </h3>

            <p>Global Business Services</p>
            <p>Technology</p>
        </div>

        <div class="job-search-tile__body">
            <div class="job-search-tile__detail">
                <p>
                    <i class="icon icon--date"></i>
                    <span class="ada-hidden">
                        Date &nbsp;
                    </span>
                    Posted 08/01/2026
                </p>

                <p>
                    <i class="icon icon--location"></i>
                    <span class="ada-hidden">
                        Location &nbsp;
                    </span>
                    Mumbai, India
                </p>
            </div>
        </div>
    </div>
    """

    jobs = adapter._extract_jobs(
        page_html,
        _company(),
    )

    assert len(jobs) == 1

    job = jobs[0]

    assert job.id == "26011393"

    assert job.title == (
        "Software Engineer III - GBS IND"
    )

    assert job.location == "Mumbai, India"

    assert job.department == "Technology"

    assert str(job.url) == (
        "https://careers.bankofamerica.com/"
        "en-us/job-detail/26011393/"
        "software-engineer-iii-gbs-ind-"
        "multiple-locations"
    )


def test_extracts_total():
    adapter = BankOfAmericaAdapter()

    assert adapter._extract_total(
        "<div>112 relevant jobs</div>"
    ) == 112

    assert adapter._extract_total(
        '<span id="span_results">151</span>'
    ) == 151


def test_discovers_next_url():
    adapter = BankOfAmericaAdapter()

    page_html = """
    <nav>
        <a href="/en-us/job-search/example">
            Previous
        </a>

        <a
            href="/en-us/job-search/example?page=whatever"
            aria-label="Next"
        >
            Next
        </a>
    </nav>
    """

    next_url = adapter._extract_next_url(
        page_html,
        (
            "https://careers.bankofamerica.com/"
            "en-us/job-search/example"
        ),
    )

    assert next_url == (
        "https://careers.bankofamerica.com/"
        "en-us/job-search/example?page=whatever"
    )