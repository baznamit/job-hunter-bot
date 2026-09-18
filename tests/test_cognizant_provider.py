from unittest.mock import Mock, patch

from models.company import (
    Company,
    CompanyCategory,
    Provider,
    ProviderConfig,
    ProviderStatus,
    ProviderType,
)
from src.providers.cognizant import CognizantAdapter


def _company() -> Company:
    return Company(
        id="cognizant",
        name="Cognizant",
        category=CompanyCategory.PRODUCT,
        priority=1,
        career_page=(
            "https://careers.cognizant.com/"
            "india-en/jobs/"
        ),
        provider=Provider(
            type=ProviderType.COGNIZANT,
            status=ProviderStatus.VERIFIED,
            config=ProviderConfig(
                base_url=(
                    "https://careers.cognizant.com/"
                    "india-en"
                )
            ),
        ),
    )


def _response(
    xml: str,
    status: int = 200,
) -> Mock:
    response = Mock()
    response.status_code = status
    response.content = xml.encode("utf-8")
    response.url = (
        "https://careers.cognizant.com/"
        "india-en/jobs/xml/?rss=true"
    )

    response.raise_for_status = Mock()

    return response


def test_cognizant_parses_jobs():
    raw = [
        {
            "title": "Postgre + Tableau",
            "date": (
                "Fri, 18 Sep 2026 "
                "05:30:16 GMT"
            ),
            "requisitionid": "00068039435",
            "url": (
                "https://careers.cognizant.com/"
                "india-en/jobs/00068039435/"
                "postgre-plus-tableau/"
            ),
            "city": "PUNE",
            "state": "Maharashtra",
            "country": "India",
        }
    ]

    jobs = CognizantAdapter().parse(
        raw,
        _company(),
    )

    assert len(jobs) == 1

    job = jobs[0]

    assert job.id == "00068039435"
    assert job.title == "Postgre + Tableau"
    assert job.location == (
        "PUNE, Maharashtra, India"
    )
    assert job.posted_at is not None


@patch(
    "src.providers.cognizant.requests.get"
)
def test_cognizant_fetches_xml(
    mock_get,
):
    xml = """
    <source>
        <job>
            <title>Software Engineer</title>
            <requisitionid>12345</requisitionid>
            <url>
                https://careers.cognizant.com/india-en/jobs/12345/software-engineer/
            </url>
            <city>MUMBAI</city>
            <state>Maharashtra</state>
            <country>India</country>
        </job>
    </source>
    """

    mock_get.return_value = _response(
        xml
    )

    jobs = CognizantAdapter().fetch_jobs(
        _company()
    )

    assert len(jobs) == 1
    assert jobs[0].id == "12345"
    assert jobs[0].location == (
        "MUMBAI, Maharashtra, India"
    )

    requested_url = (
        mock_get.call_args.args[0]
    )

    assert requested_url.endswith(
        "/jobs/xml/?rss=true"
    )
