from models.company import (
    Company,
    CompanyCategory,
    Provider,
    ProviderConfig,
    ProviderStatus,
    ProviderType,
)
from src.providers.talentbrew import (
    TalentBrewAdapter,
)


def _company(
    base_url: str,
    page_size: int,
) -> Company:
    return Company(
        id="test",
        name="Test Co",
        category=CompanyCategory.BANKING,
        priority=1,
        career_page=base_url,
        provider=Provider(
            type=ProviderType.TALENTBREW,
            status=ProviderStatus.PARTIAL,
            config=ProviderConfig(
                base_url=base_url,
                page_size=page_size,
            ),
        ),
    )


def test_extracts_citi_job():
    adapter = TalentBrewAdapter()

    company = _company(
        "https://jobs.citi.com",
        15,
    )

    page_html = """
    <li class="sr-job-item">
        <h3 class="sr-job-item__title">
            <a
                class="sr-job-item__link"
                href="/job/mumbai/software-engineer/287/99487065040"
                data-job-id="99487065040"
            >
                Software Engineer
            </a>
        </h3>

        <span
            class="sr-job-item__facet
                   sr-job-item__facet-icon
                   sr-job-location"
        >
            Mumbai, Maharashtra, India
        </span>
    </li>
    """

    jobs = adapter._extract_jobs(
        page_html,
        company,
    )

    assert len(jobs) == 1
    assert jobs[0].id == "99487065040"
    assert jobs[0].title == "Software Engineer"
    assert jobs[0].location == (
        "Mumbai, Maharashtra, India"
    )
    assert str(jobs[0].url) == (
        "https://jobs.citi.com/"
        "job/mumbai/software-engineer/"
        "287/99487065040"
    )


def test_extracts_blackrock_job():
    adapter = TalentBrewAdapter()

    company = _company(
        "https://careers.blackrock.com",
        10,
    )

    page_html = """
    <li class="section3__search-results-li">
        <a
            class="section3__search-results-a"
            href="/job/mumbai/artificial-intelligence-engineer/45831/97556635296"
            data-job-id="97556635296"
        >
            <h2 class="section3__job-title">
                Artificial Intelligence Engineer
            </h2>

            <span class="job-location">
                <span>Location:</span>
                <span class="section3__job-info">
                    Mumbai, Maharashtra
                </span>
            </span>

            <span class="job-category">
                <span>Team:</span>
                <span class="section3__job-info">
                    Software Engineering
                </span>
            </span>
        </a>
    </li>
    """

    jobs = adapter._extract_jobs(
        page_html,
        company,
    )

    assert len(jobs) == 1

    job = jobs[0]

    assert job.id == "97556635296"
    assert job.title == (
        "Artificial Intelligence Engineer"
    )
    assert job.location == (
        "Mumbai, Maharashtra"
    )
    assert job.department == (
        "Software Engineering"
    )


def test_extracts_total_results():
    adapter = TalentBrewAdapter()

    assert adapter._extract_total(
        '<h2 class="sr-heading">3476 Results</h2>'
    ) == 3476

    assert adapter._extract_total(
        (
            '<h1 class="section3__search-results-heading">'
            '310 jobs found'
            '</h1>'
        )
    ) == 310