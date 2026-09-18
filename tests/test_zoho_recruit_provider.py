from unittest.mock import Mock, patch

from models.company import (
    Company,
    CompanyCategory,
    Provider,
    ProviderConfig,
    ProviderStatus,
    ProviderType,
)
from src.providers.zoho_recruit import (
    ZohoRecruitAdapter,
)


def _company() -> Company:
    return Company(
        id="wissen",
        name="Wissen Technology",
        category=CompanyCategory.PRODUCT,
        priority=1,
        career_page=(
            "https://careers.wissen.com/"
        ),
        provider=Provider(
            type=(
                ProviderType.ZOHO_RECRUIT
            ),
            status=(
                ProviderStatus.VERIFIED
            ),
            config=ProviderConfig(
                api_url=(
                    "https://wissen."
                    "zohorecruit.in/recruit/"
                    "v2/public/Job_Openings"
                ),
                page_name="Careers",
                source="CareerSite",
            ),
        ),
    )


def _response(
    payload: dict,
    status: int = 200,
) -> Mock:
    response = Mock()

    response.status_code = status
    response.url = (
        "https://wissen.zohorecruit.in/"
        "recruit/v2/public/Job_Openings"
    )

    response.json.return_value = payload
    response.raise_for_status = Mock()

    return response


def test_zoho_recruit_parses_jobs():
    raw = {
        "code": "SUCCESS",
        "data": [
            {
                "id": "80238000189758005",
                "Posting_Title": (
                    "Java Full Stack Developer"
                ),
                "Job_Opening_Name": (
                    "Java Full Stack Developer"
                ),
                "City": "Mumbai",
                "Country": "India",
                "Job_Type": "Full time",
                "Date_Opened": "07/09/2026",
                "$url": (
                    "https://careers.wissen.com/"
                    "jobs/Careers/"
                    "80238000189758005/"
                    "Java-Full-Stack-Developer"
                ),
            }
        ],
    }

    jobs = (
        ZohoRecruitAdapter().parse(
            raw,
            _company(),
        )
    )

    assert len(jobs) == 1

    job = jobs[0]

    assert (
        job.id
        == "80238000189758005"
    )
    assert (
        job.title
        == "Java Full Stack Developer"
    )
    assert (
        job.location
        == "Mumbai, India"
    )
    assert (
        job.employment_type
        == "Full time"
    )
    assert job.posted_at is not None


@patch(
    "src.providers.zoho_recruit."
    "requests.get"
)
def test_zoho_recruit_fetches_jobs(
    mock_get,
):
    mock_get.return_value = _response(
        {
            "code": "SUCCESS",
            "data": [
                {
                    "id": "123",
                    "Posting_Title": (
                        "Technical "
                        "Business Analyst"
                    ),
                    "City": "Mumbai",
                    "Country": "India",
                    "$url": (
                        "https://careers."
                        "wissen.com/jobs/"
                        "Careers/123/test"
                    ),
                }
            ],
        }
    )

    jobs = (
        ZohoRecruitAdapter()
        .fetch_jobs(
            _company()
        )
    )

    assert len(jobs) == 1
    assert jobs[0].id == "123"

    _, kwargs = (
        mock_get.call_args
    )

    assert kwargs["params"] == {
        "pagename": "Careers",
        "source": "CareerSite",
    }
