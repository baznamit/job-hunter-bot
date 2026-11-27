import json
from unittest.mock import patch

import pytest
import requests

from research.loader import load_registry
from src.filters import JobFilter
from src.providers.workday import WorkdayAdapter, WorkdayRequestPolicy


_TOTAL = 323
_ENDPOINT = (
    "https://cisco.wd5.myworkdayjobs.com/"
    "wday/cxs/cisco/Cisco_Careers/jobs"
)


def _response(url, payload):
    response = requests.Response()
    response.status_code = 200
    response.url = url
    response.headers = {"Content-Type": "application/json"}
    response._content = json.dumps(payload).encode("utf-8")
    response.encoding = "utf-8"
    return response


@pytest.mark.parametrize("secondary_city", ["Bangalore", "Bengaluru"])
def test_cisco_workday_fetch_covers_inventory_and_preserves_canonical_urls(
    secondary_city,
):
    company = next(
        company
        for company in load_registry().companies
        if company.id == "cisco"
    )
    adapter = WorkdayAdapter(
        WorkdayRequestPolicy(pacing_seconds=0, max_attempts=1)
    )
    offsets = []

    def fake_post(url, *, json, headers, timeout):
        assert url == _ENDPOINT
        assert headers["Referer"] == (
            "https://cisco.wd5.myworkdayjobs.com/en-US/Cisco_Careers"
        )
        assert json["searchText"] == ""
        assert json["appliedFacets"] == {}
        assert json["limit"] == 20
        offset = json["offset"]
        offsets.append(offset)
        postings = []
        for index in range(offset, min(offset + json["limit"], _TOTAL)):
            if index == 0:
                external_path = (
                    "/job/Hyderabad-India/"
                    "Software-Engineer_2025113-1"
                )
                locations_text = "2 Locations"
            else:
                external_path = (
                    f"/job/Bangalore-India/Cisco-Role-{index}"
                )
                locations_text = "Bangalore, India"
            postings.append(
                {
                    "externalPath": external_path,
                    "title": (
                        "Software Engineer"
                        if index == 0
                        else f"Cisco Role {index}"
                    ),
                    "locationsText": locations_text,
                }
            )
        return _response(
            url,
            {"total": _TOTAL, "jobPostings": postings},
        )

    def fake_get(url, *, headers, timeout):
        assert url == (
            "https://cisco.wd5.myworkdayjobs.com/wday/cxs/cisco/"
            "Cisco_Careers/job/Hyderabad-India/Software-Engineer_2025113-1"
        )
        assert headers["Referer"] == (
            "https://cisco.wd5.myworkdayjobs.com/en-US/Cisco_Careers"
        )
        return _response(
            url,
            {
                "jobPostingInfo": {
                    "location": "Hyderabad, India",
                    "additionalLocations": [f"{secondary_city}, India"],
                }
            },
        )

    with (
        patch(
            "src.providers.workday.requests.post",
            side_effect=fake_post,
        ) as post,
        patch(
            "src.providers.workday.requests.get",
            side_effect=fake_get,
        ) as detail,
    ):
        jobs, report = adapter.fetch_jobs_with_report(company)

    assert len(jobs) == _TOTAL
    assert report.coverage_status == "complete"
    assert post.call_count == 17
    assert sorted(offsets) == list(range(0, _TOTAL, 20))
    assert detail.call_count == 1
    assert jobs[0].id == "/job/Hyderabad-India/Software-Engineer_2025113-1"
    assert str(jobs[0].url) == (
        "https://cisco.wd5.myworkdayjobs.com/en-US/"
        "Cisco_Careers/job/Hyderabad-India/"
        "Software-Engineer_2025113-1"
    )
    assert jobs[0].location == f"Hyderabad, India | {secondary_city}, India"

    job_filter = JobFilter()
    job_filter.allow_india = False
    assert job_filter.should_include(jobs[0])
    assert not job_filter.should_include(
        jobs[0].model_copy(update={"location": "Hyderabad, India"})
    )
