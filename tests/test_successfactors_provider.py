from src.providers.successfactors import (
    SuccessFactorsAdapter,
)


def test_extract_job_urls_decodes_html_entities():
    html = """
    <a href="/Nomura/job/Mumbai-FIN_Business-Finance-&amp;-Control_AN/1418555300/">
        Job
    </a>
    """

    urls = (
        SuccessFactorsAdapter()
        ._extract_job_urls(
            html,
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

    # Use your existing test company helper here.
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