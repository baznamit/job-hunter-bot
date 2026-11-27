from datetime import datetime, timezone
from urllib.parse import unquote

from models.company import Company
from src.providers.turbohire import TurboHireAdapter


def _company() -> Company:
    return Company.model_validate(
        {
            "id": "navi",
            "name": "Navi",
            "category": "FinTech",
            "priority": 1,
            "career_page": "https://navi.com/careers/",
            "provider": {
                "type": "turbohire",
                "status": "verified",
                "config": {
                    "base_url": "https://navi.turbohire.co",
                    "organization": "navi",
                },
            },
        }
    )


def test_parses_public_turbohire_job():
    raw = {
        "Total": 1,
        "Result": [
            {
                "JobId": "job-123",
                "JobIdObfuscated": "a%2Fb%2Bc",
                "JobTitle": "Software Engineer",
                "Department": "Engineering",
                "PublishedDate": "2026-11-25T05:16:47.7368133Z",
                "Location": (
                    '[{"Address":"Bengaluru, Karnataka, India",'
                    '"PlaceId":null},{"Address":"Mumbai, India"}]'
                ),
            }
        ],
    }

    jobs = TurboHireAdapter().parse(raw, _company())

    assert len(jobs) == 1
    assert jobs[0].id == "job-123"
    assert jobs[0].title == "Software Engineer"
    assert jobs[0].location == "Bengaluru, Karnataka, India, Mumbai, India"
    assert jobs[0].department == "Engineering"
    assert jobs[0].posted_at == datetime(
        2026, 11, 25, 5, 16, 47, 736813, tzinfo=timezone.utc
    )
    assert unquote(str(jobs[0].url)).endswith("/job/publicjobs/a/b+c")


def test_ignores_incomplete_turbohire_jobs():
    raw = {
        "Total": 2,
        "Result": [
            {"JobId": "missing-title"},
            {"JobTitle": "missing-id"},
            None,
        ],
    }

    assert TurboHireAdapter().parse(raw, _company()) == []


def test_fetches_public_feed_using_anonymous_token(monkeypatch):
    class Response:
        status_code = 200
        url = "https://thapi.azurewebsites.net/test"
        headers = {}

        def __init__(self, data):
            self.data = data

        def json(self):
            return self.data

        def raise_for_status(self):
            return None

    get_calls = []
    post_calls = []

    def fake_get(url, **kwargs):
        get_calls.append((url, kwargs))
        if url.endswith("/api/token/noauth"):
            return Response({"access_token": "test-token"})
        return Response({"OrgID": "org-123"})

    def fake_post(url, **kwargs):
        post_calls.append((url, kwargs))
        return Response({"Total": 1, "Result": [{"JobId": "job-1"}]})

    monkeypatch.setattr("src.providers.turbohire.requests.get", fake_get)
    monkeypatch.setattr("src.providers.turbohire.requests.post", fake_post)

    raw = TurboHireAdapter()._fetch_raw(_company())

    assert raw["Total"] == 1
    assert len(get_calls) == 2
    assert get_calls[1][1]["params"] == {"accountName": "navi"}
    assert get_calls[1][1]["headers"]["Authorization"] == "Bearer test-token"
    assert get_calls[1][1]["headers"]["Origin"] == "https://navi.turbohire.co"
    assert post_calls[0][1]["params"] == {"orgId": "org-123", "pageType": 0}
