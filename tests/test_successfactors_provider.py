from models.company import (
    Company,
    CompanyCategory,
    Provider,
    ProviderConfig,
    ProviderStatus,
    ProviderType,
)
from src.providers.successfactors import (
    SuccessFactorsAdapter,
)


def _company(
    provider_type: ProviderType,
    **config,
) -> Company:
    return Company(
        id="test",
        name="Test Co",
        category=CompanyCategory.SAAS,
        priority=1,
        career_page="https://example.com/careers",
        provider=Provider(
            type=provider_type,
            status=ProviderStatus.PARTIAL,
            config=ProviderConfig(**config),
        ),
    )


def test_extract_job_urls_decodes_html_entities():
    page_html = """
    <a href="/Nomura/job/Mumbai-FIN_Business-Finance-&amp;-Control_AN/1418555300/">
        Job
    </a>
    """

    urls = (
        SuccessFactorsAdapter()
        ._extract_job_urls(
            page_html,
            "https://careers.nomura.com",
        )
    )

    assert urls == [
        (
            "https://careers.nomura.com/"
            "Nomura/job/"
            "Mumbai-FIN_Business-Finance-&-Control_AN/"
            "1418555300/"
        )
    ]


def test_successfactors_listing_pagination_url():
    adapter = SuccessFactorsAdapter()

    company = _company(
        ProviderType.SUCCESSFACTORS,
        base_url="https://careers.nomura.com",
        listing_path=(
            "/Nomura/go/"
            "Career-Opportunities-India/"
            "9050900/"
        ),
        page_size=100,
    )

    assert adapter._listing_url(
        company,
        0,
    ) == (
        "https://careers.nomura.com/"
        "Nomura/go/"
        "Career-Opportunities-India/"
        "9050900/"
    )

    assert adapter._listing_url(
        company,
        100,
    ) == (
        "https://careers.nomura.com/"
        "Nomura/go/"
        "Career-Opportunities-India/"
        "9050900/100/"
    )

def test_extract_location_falls_back_to_nomura_url():
    adapter = SuccessFactorsAdapter()

    location = adapter._extract_location(
        "<html><body>No location field</body></html>",
        (
            "https://careers.nomura.com/"
            "Nomura/job/"
            "Mumbai-Software-Engineer/"
            "1421393100/"
        ),
    )

    assert location == "Mumbai"

def test_extract_location_rejects_job_description_text():
    adapter = SuccessFactorsAdapter()

    page_html = """
    <html>
        <body>
            Location:
            Knowledge of Equity Trading Markets –
            especially Compliance related issues and
            challenges Python
        </body>
    </html>
    """

    location = adapter._extract_location(
        page_html,
        (
            "https://careers.nomura.com/"
            "Nomura/job/"
            "Mumbai-Software-Engineer/"
            "1421393100/"
        ),
    )

    assert location == "Mumbai"