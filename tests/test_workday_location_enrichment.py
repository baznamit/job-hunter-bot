from types import SimpleNamespace
from unittest.mock import patch

from models import Job
from src.filters import JobFilter
from src.providers.workday import WorkdayAdapter


def _company():
    return SimpleNamespace(
        id="duckcreek",
        provider=SimpleNamespace(
            config=SimpleNamespace(
                tenant="duckcreek",
                cluster="wd1",
                board="duckcreekcareers",
            )
        ),
    )


def test_duckcreek_multiple_locations():
    data = {
        "jobPostingInfo": {
            "location": "Mumbai, India",
            "additionalLocations": [
                "Bengaluru, India",
                "Mumbai, India",
            ],
            "country": {
                "descriptor": "India",
            },
        }
    }

    location = WorkdayAdapter._locations_from_detail(data)

    assert location == "Mumbai, India | Bengaluru, India"


def test_bakerhughes_country_coded_locations():
    data = {
        "jobPostingInfo": {
            "location": (
                "IN-MH-MUMBAI-HIRANANDANI BUSINESS PARK POWAI"
            ),
            "additionalLocations": [
                "IN-KA-BANGALORE-NEON BUILDING WEST TOWER",
                "IN-Maharashtra-Pune-7th Floor",
            ],
            "jobRequisitionLocation": {
                "country": {
                    "alpha2Code": "IN",
                }
            },
        }
    }

    location = WorkdayAdapter._locations_from_detail(data)

    assert location == (
        "Mumbai, India | Bengaluru, India | Pune, India"
    )


def test_unverified_country_does_not_infer_india():
    data = {
        "jobPostingInfo": {
            "location": "IN-MH-MUMBAI-SITE",
            "additionalLocations": [],
            "jobRequisitionLocation": {
                "country": {
                    "alpha2Code": "US",
                }
            },
        }
    }

    location = WorkdayAdapter._locations_from_detail(data)

    assert location == "IN-MH-MUMBAI-SITE"


def test_only_ambiguous_locations_trigger_detail_fetch():
    adapter = WorkdayAdapter()

    postings = [
        {
            "externalPath": "/job/Mumbai-India/Job-1",
            "locationsText": "2 Locations",
            "_workday_board": "duckcreekcareers",
        },
        {
            "externalPath": "/job/Bengaluru-India/Job-2",
            "locationsText": "Bengaluru, India",
            "_workday_board": "duckcreekcareers",
        },
    ]

    with patch.object(
        adapter,
        "_fetch_detail_location",
        return_value="Mumbai, India | Bengaluru, India",
    ) as mock_fetch:
        adapter._enrich_ambiguous_locations(
            _company(),
            postings,
        )

    assert mock_fetch.call_count == 1

    assert postings[0]["_resolved_location"] == (
        "Mumbai, India | Bengaluru, India"
    )

    assert "_resolved_location" not in postings[1]


def test_failed_enrichment_preserves_original_location():
    adapter = WorkdayAdapter()

    postings = [
        {
            "externalPath": "/job/Mumbai-India/Job-1",
            "locationsText": "2 Locations",
            "_workday_board": "duckcreekcareers",
        }
    ]

    with patch.object(
        adapter,
        "_fetch_detail_location",
        return_value=None,
    ):
        adapter._enrich_ambiguous_locations(
            _company(),
            postings,
        )

    assert postings[0]["locationsText"] == "2 Locations"
    assert "_resolved_location" not in postings[0]


def test_enriched_bakerhughes_java_role_passes_filter():
    job = Job(
        id="R160606",
        title=(
            "Full Stack Developer "
            "(Angular, Java, Spring Boot, AWS, AI Tools)"
        ),
        company="Baker Hughes",
        location=(
            "Mumbai, India | Bengaluru, India | Pune, India"
        ),
        url=(
            "https://bakerhughes.wd5.myworkdayjobs.com/"
            "en-US/BakerHughes/job/example"
        ),
    )

    result = JobFilter().evaluate(job)

    assert result.included is True


def test_single_location_site_code_triggers_enrichment():
    adapter = WorkdayAdapter()

    postings = [
        {
            "externalPath": "/job/IN-MH-MUMBAI/Job-1",
            "locationsText": (
                "IN-MH-MUMBAI-HIRANANDANI BUSINESS PARK POWAI"
            ),
            "_workday_board": "BakerHughes",
        },
        {
            "externalPath": "/job/Bengaluru-India/Job-2",
            "locationsText": "Bengaluru, India",
            "_workday_board": "BakerHughes",
        },
    ]

    with patch.object(
        adapter,
        "_fetch_detail_location",
        return_value="Mumbai, India",
    ) as mock_fetch:
        adapter._enrich_ambiguous_locations(
            _company(),
            postings,
        )

    assert mock_fetch.call_count == 1
    assert postings[0]["_resolved_location"] == "Mumbai, India"
    assert "_resolved_location" not in postings[1]


def test_single_location_detail_failure_preserves_original():
    adapter = WorkdayAdapter()

    original = "IN-KA-BANGALORE-NEON BUILDING WEST TOWER"

    postings = [
        {
            "externalPath": "/job/IN-KA-BANGALORE/Job-1",
            "locationsText": original,
            "_workday_board": "BakerHughes",
        }
    ]

    with patch.object(
        adapter,
        "_fetch_detail_location",
        return_value=None,
    ):
        adapter._enrich_ambiguous_locations(
            _company(),
            postings,
        )

    assert postings[0]["locationsText"] == original
    assert "_resolved_location" not in postings[0]


def test_single_location_country_mismatch_not_normalized():
    from unittest.mock import Mock

    adapter = WorkdayAdapter()

    posting = {
        "externalPath": "/job/IN-MH-MUMBAI/Job-1",
        "locationsText": "IN-MH-MUMBAI-SITE",
    }

    response = Mock()
    response.json.return_value = {
        "jobPostingInfo": {
            "location": "IN-MH-MUMBAI-SITE",
            "country": {"descriptor": "United States"},
            "jobRequisitionLocation": {
                "country": {"alpha2Code": "US"}
            },
        }
    }

    with patch(
        "src.providers.workday.requests.get",
        return_value=response,
    ):
        with patch.object(
            adapter,
            "_check_response",
        ):
            result = adapter._fetch_detail_location(
                _company(),
                "duckcreekcareers",
                posting,
            )

    assert result is None


def test_non_site_code_requires_no_detail_request():
    adapter = WorkdayAdapter()

    postings = [
        {
            "externalPath": "/job/US-CA/Job-1",
            "locationsText": "San Francisco, United States",
            "_workday_board": "duckcreekcareers",
        },
        {
            "externalPath": "/job/IN-MH/Job-2",
            "locationsText": "Mumbai, India",
            "_workday_board": "duckcreekcareers",
        },
    ]

    with patch.object(
        adapter,
        "_fetch_detail_location",
    ) as mock_fetch:
        adapter._enrich_ambiguous_locations(
            _company(),
            postings,
        )

    mock_fetch.assert_not_called()
