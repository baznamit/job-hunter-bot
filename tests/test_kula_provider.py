from unittest.mock import patch

from models.company import (
    Company,
    CompanyCategory,
    Provider,
    ProviderConfig,
    ProviderStatus,
    ProviderType,
)
from src.providers import KulaAdapter


def _company() -> Company:
    return Company(
        id="clevertap",
        name="CleverTap",
        category=CompanyCategory.SAAS,
        priority=2,
        enabled=True,
        career_page=(
            "https://careers.kula.ai/"
            "clevertap"
        ),
        provider=Provider(
            type=ProviderType.KULA,
            status=ProviderStatus.VERIFIED,
            config=ProviderConfig(
                base_url=(
                    "https://careers.kula.ai/"
                    "clevertap"
                ),
            ),
        ),
    )


def test_kula_extracts_jobs_from_server_state():
    adapter = KulaAdapter()

    html = r'''
    <html>
    <script>
    {
      "id":12616,
      "account_id":1350,
      "title":"DevOps Engineer",
      "launch_at":"2025-08-26T11:21:53.000Z",
      "employment_type":"full_time",
      "department":"Engineering",
      "location":"Mumbai, Maharashtra, India",
      "country_code":"IN",
      "city":"Mumbai",
      "remote":false,
      "workplace":"office"
    }
    </script>
    </html>
    '''

    jobs = adapter._extract_jobs(
        html
    )

    assert len(jobs) == 1

    assert jobs[0]["id"] == "12616"
    assert (
        jobs[0]["title"]
        == "DevOps Engineer"
    )
    assert jobs[0]["location"] == (
        "Mumbai, Maharashtra, India"
    )
    assert (
        jobs[0]["department"]
        == "Engineering"
    )
    assert jobs[0]["remote"] is False


def test_kula_parse():
    adapter = KulaAdapter()
    company = _company()

    raw = {
        "board_url": (
            "https://careers.kula.ai/"
            "clevertap"
        ),
        "jobs": [
            {
                "id": "12616",
                "title":
                    "DevOps Engineer",
                "location":
                    "Mumbai, Maharashtra, India",
                "department":
                    "Engineering",
                "employment_type":
                    "full_time",
                "launch_at":
                    "2025-08-26T11:21:53.000Z",
                "remote": False,
                "workplace": "office",
            }
        ],
    }

    jobs = adapter.parse(
        raw,
        company,
    )

    assert len(jobs) == 1

    job = jobs[0]

    assert job.id == "12616"
    assert (
        job.company
        == "CleverTap"
    )
    assert (
        job.title
        == "DevOps Engineer"
    )
    assert job.location == (
        "Mumbai, Maharashtra, India"
    )
    assert (
        job.department
        == "Engineering"
    )
    assert (
        job.employment_type
        == "full_time"
    )
    assert job.remote is False

    assert str(job.url) == (
        "https://careers.kula.ai/"
        "clevertap/12616/"
    )

    assert job.posted_at is not None


def test_kula_deduplicates_jobs():
    adapter = KulaAdapter()
    company = _company()

    item = {
        "id": "12616",
        "title":
            "DevOps Engineer",
        "location":
            "Mumbai, Maharashtra, India",
    }

    jobs = adapter.parse(
        {
            "board_url": (
                "https://careers.kula.ai/"
                "clevertap"
            ),
            "jobs": [
                item,
                item.copy(),
            ],
        },
        company,
    )

    assert len(jobs) == 1


def test_kula_remote_workplace():
    adapter = KulaAdapter()
    company = _company()

    jobs = adapter.parse(
        {
            "board_url": (
                "https://careers.kula.ai/"
                "clevertap"
            ),
            "jobs": [
                {
                    "id": "999",
                    "title":
                        "Software Engineer",
                    "location":
                        "India",
                    "remote": False,
                    "workplace":
                        "remote",
                }
            ],
        },
        company,
    )

    assert len(jobs) == 1
    assert jobs[0].remote is True


@patch(
    "src.providers.kula.requests.get"
)
def test_kula_fetches_public_board(
    mock_get,
):
    response = mock_get.return_value

    response.status_code = 200
    response.url = (
        "https://careers.kula.ai/"
        "clevertap"
    )

    response.text = r'''
    <script>
    {
      "id":12616,
      "title":"DevOps Engineer",
      "location":"Mumbai, Maharashtra, India",
      "department":"Engineering",
      "remote":false
    }
    </script>
    '''

    response.raise_for_status.return_value = (
        None
    )

    adapter = KulaAdapter()

    jobs = adapter.fetch_jobs(
        _company()
    )

    assert len(jobs) == 1

    assert (
        jobs[0].title
        == "DevOps Engineer"
    )

    mock_get.assert_called_once()

    args, kwargs = (
        mock_get.call_args
    )

    assert args[0] == (
        "https://careers.kula.ai/"
        "clevertap"
    )

    assert (
        kwargs["allow_redirects"]
        is True
    )