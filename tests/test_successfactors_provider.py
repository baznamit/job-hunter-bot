from unittest.mock import patch

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


def test_successfactors_query_pagination_url():
    adapter = SuccessFactorsAdapter()

    company = _company(
        ProviderType.SUCCESSFACTORS,
        base_url=(
            "https://careers.capgemini.com"
        ),
        listing_path="/search/",
        page_size=25,
        pagination_mode="query",
        pagination_param="startrow",
    )

    assert adapter._listing_url(
        company,
        0,
    ) == (
        "https://careers.capgemini.com/"
        "search/"
    )

    assert adapter._listing_url(
        company,
        25,
    ) == (
        "https://careers.capgemini.com/"
        "search/?startrow=25"
    )

    assert adapter._listing_url(
        company,
        50,
    ) == (
        "https://careers.capgemini.com/"
        "search/?startrow=50"
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


def test_extract_location_from_generic_successfactors_url():
    adapter = SuccessFactorsAdapter()

    location = adapter._extract_location(
        (
            "<html><body>"
            "No structured location field"
            "</body></html>"
        ),
        (
            "https://careers.capgemini.com/"
            "job/Mumbai-SAP-Concur/"
            "1389183133/"
        ),
    )

    assert location == "Mumbai"


def test_extract_location_from_ltm_successfactors_url():
    adapter = SuccessFactorsAdapter()

    location = adapter._extract_location(
        (
            "<html><body>"
            "No structured location field"
            "</body></html>"
        ),
        (
            "https://careers.ltm.com/"
            "job/Bengaluru-Senior-Software-Engineer-Karn/"
            "679605001/"
        ),
    )

    assert location == "Bengaluru"


def test_location_from_job_url():
    adapter = SuccessFactorsAdapter()

    assert (
        adapter._location_from_job_url(
            (
                "https://careers.capgemini.com/"
                "job/Mumbai-SAP-Concur/"
                "1389183133/"
            )
        )
        == "Mumbai"
    )

    assert (
        adapter._location_from_job_url(
            (
                "https://careers.ltm.com/"
                "job/Bengaluru-Senior-Software-Engineer-Karn/"
                "679605001/"
            )
        )
        == "Bengaluru"
    )


def test_successfactors_search_location_filter():
    adapter = SuccessFactorsAdapter()

    locations = [
        "Mumbai",
        "Bangalore",
        "Bengaluru",
    ]

    assert adapter._matches_search_locations(
        (
            "https://careers.capgemini.com/"
            "job/Mumbai-SAP-Concur/"
            "1389183133/"
        ),
        locations,
    )

    assert adapter._matches_search_locations(
        (
            "https://careers.capgemini.com/"
            "job/Bangalore-Java-Developer/"
            "123456/"
        ),
        locations,
    )

    assert not adapter._matches_search_locations(
        (
            "https://careers.capgemini.com/"
            "job/Pune-Java-Developer/"
            "123456/"
        ),
        locations,
    )


@patch.object(
    SuccessFactorsAdapter,
    "_fetch_html",
)
def test_location_filter_does_not_stop_pagination(
    mock_fetch_html,
):
    adapter = SuccessFactorsAdapter()

    company = _company(
        ProviderType.SUCCESSFACTORS,
        base_url=(
            "https://careers.example.com"
        ),
        listing_path="/search/",
        page_size=2,
        pagination_mode="query",
        pagination_param="startrow",
        search_locations=[
            "Mumbai",
        ],
    )

    mock_fetch_html.side_effect = [
        """
        <a href="/job/Pune-One/1/">One</a>
        <a href="/job/Pune-Two/2/">Two</a>
        """,
        """
        <a href="/job/Mumbai-Three/3/">Three</a>
        """,
    ]

    urls = adapter._fetch_raw(
        company
    )

    assert urls == [
        (
            "https://careers.example.com/"
            "job/Mumbai-Three/3/"
        )
    ]

    assert mock_fetch_html.call_count == 2

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