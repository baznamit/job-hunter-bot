import json
import random
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import requests

from models import CompanyRegistry
from models.company import Company, ProviderType
from src.filters import JobFilter
from src.main import _ADAPTERS, _run_company, _send_notifications, _settings
from src.providers.exceptions import ProviderTemporaryError
from src.providers.publicis_sapient import API, PublicisSapientAdapter
from src.recovery_store import RecoveryStore
from src.store import SeenStore

ROOT = Path(__file__).resolve().parent.parent

# City lists per requisition mirror the 27 India requisitions (93 documents)
# observed on 2026-11-27; the first city is the primary (id == jobId) record.
_VERIFIED_GROUPS = [
    "Gurgaon/Bengaluru/Noida",
    "Gurgaon/Noida/Bengaluru",
    "Bengaluru/Gurgaon/Noida",
    "Gurgaon/Bengaluru/Noida",
    "Noida/Gurgaon/Bengaluru/Pune/Hyderabad",
    "Gurgaon/Noida/Bengaluru",
    "Bengaluru",
    "Hyderabad",
    "Gurgaon/Bengaluru/Pune/Hyderabad/Kolkata/Chennai",
    "Noida/Gurgaon/Bengaluru/Mumbai/Chennai/Pune/Hyderabad/Kolkata",
    "Bengaluru/Gurgaon/Noida/Mumbai/Pune/Hyderabad/Chennai/Kolkata",
    "Bengaluru/Gurgaon/Hyderabad/Pune/Noida",
    "Mumbai",
    "Gurgaon",
    "Gurgaon",
    "Gurgaon",
    "Gurgaon",
    "Pune/Gurgaon/Noida/Bengaluru/Mumbai/Chennai/Kolkata/Hyderabad",
    "Gurgaon/Bengaluru/Pune/Hyderabad/Noida",
    "Gurgaon/Bengaluru/Noida/Pune/Hyderabad",
    "Gurgaon/Bengaluru/Mumbai/Hyderabad/Kolkata/Pune/Noida/Chennai",
    "Gurgaon",
    "Gurgaon",
    "Bengaluru",
    "Gurgaon/Bengaluru/Mumbai/Noida/Hyderabad/Pune/Chennai/Kolkata",
    "Bengaluru",
    "Gurgaon",
]

_REGIONS = {
    "Gurgaon": "Haryana",
    "Bengaluru": "Karnataka",
    "Noida": "Uttar Pradesh",
    "Hyderabad": "Telangana",
    "Mumbai": "Maharashtra",
    "Pune": "Maharashtra",
    "Kolkata": "West Bengal",
    "Chennai": "Tamil Nadu",
}


def company(**config):
    return Company.model_validate({
        "id": "publicissapient",
        "name": "Publicis Sapient",
        "category": "Product",
        "priority": 2,
        "career_page": "https://careers.publicissapient.com/job-search?country=India",
        "provider": {
            "type": "publicis_sapient",
            "status": "implemented",
            "config": config,
        },
    })


def doc(number, city="Bengaluru", suffix=None, title="Senior Associate Software Engineer"):
    job_id = f"2026-{number}"
    doc_id = job_id if suffix is None else f"{job_id}-{suffix}"
    slug = "senior-associate-software-engineer"
    return {
        "id": doc_id,
        "jobId": job_id,
        "name": title,
        "typeOfEmployment": "Full-time",
        "experienceLevel": "Associate Level",
        "city": city,
        "region": _REGIONS[city],
        "countryName": "India",
        "displayLocation": f"{city}, {_REGIONS[city]}, India",
        "jobUrl": f"https://sapient-publicisgroupe.icims.com/jobs/{number}/job/login",
        "releasedDate": "2026-07-22T06:23:00Z",
        "teams": "Technology and Engineering",
        "jobDetailUrl": f"/job-details/{doc_id}-{slug}-{city.lower()}",
    }


def group(number, cities):
    return [
        doc(number, city, None if index == 0 else 1000000 + index)
        for index, city in enumerate(cities)
    ]


def verified_inventory():
    docs = []
    for index, cities in enumerate(_VERIFIED_GROUPS):
        docs.extend(group(144900 + index, cities.split("/")))
    # The live index sorts primary documents before city variants.
    return sorted(docs, key=lambda item: (item["id"] != item["jobId"], item["id"]))


def response(docs, total, start, *, exact=True, status=200):
    result = Mock()
    result.status_code = status
    result.url = API
    result.headers = {"Content-Type": "application/json;charset=utf-8"}
    result.json.return_value = {
        "response": {
            "numFound": total,
            "start": start,
            "numFoundExact": exact,
            "docs": docs,
        }
    }
    result.raise_for_status = Mock()
    return result


def paged(docs, rows=20, total=None):
    total = len(docs) if total is None else total
    return [
        response(docs[start:start + rows], total, start)
        for start in range(0, max(len(docs), 1), rows)
    ]


def fetch(responses, **config):
    session = Mock()
    session.get.side_effect = responses
    with patch("src.providers.publicis_sapient.requests.Session") as factory:
        factory.return_value.__enter__.return_value = session
        jobs = PublicisSapientAdapter().fetch_jobs(company(**config))
    return jobs, session


def fail(responses, error, match, **config):
    session = Mock()
    session.get.side_effect = responses
    with patch("src.providers.publicis_sapient.requests.Session") as factory:
        factory.return_value.__enter__.return_value = session
        with pytest.raises(error, match=match) as raised:
            PublicisSapientAdapter().fetch_jobs(company(**config))
    return raised, session


def test_complete_verified_inventory_groups_93_records_into_27_jobs(capsys):
    docs = verified_inventory()
    assert len(docs) == 93

    jobs, session = fetch(paged(docs))

    offsets = [call.kwargs["params"]["start"] for call in session.get.call_args_list]
    assert offsets == [0, 20, 40, 60, 80]
    first = session.get.call_args_list[0]
    assert first.args == (API,)
    assert first.kwargs["params"] == {
        "country": "India", "start": 0, "rows": 20,
        "searchType": "/search", "lang": "en", "q": "",
    }
    assert len(jobs) == 27
    assert len({job.id for job in jobs}) == 27
    assert len({str(job.url) for job in jobs}) == 27
    assert sum(len(job.location.split(" | ")) for job in jobs) == 93
    out = capsys.readouterr().out
    assert "[PUBLICIS] Publicis Sapient: status=complete pages=5" in out
    assert "raw_records=93 records=93 total=93 requisitions=27" in out


def test_exact_page_boundary_stops_without_extra_request():
    docs = [doc(n) for n in range(1, 41)]
    jobs, session = fetch(paged(docs))
    assert session.get.call_count == 2
    assert len(jobs) == 40


def test_zero_inventory_returns_no_jobs():
    jobs, session = fetch([response([], 0, 0)])
    assert jobs == [] and session.get.call_count == 1


@pytest.mark.parametrize(
    ("responses", "match"),
    [
        ([response([doc(1), doc(2)], 3, 0), response([doc(3)], 4, 2)], "inventory changed"),
        ([response([doc(1), doc(2)], 4, 0), response([doc(1), doc(2)], 4, 2)], "stalled"),
        ([response([doc(1), doc(2)], 4, 0), response([doc(2), doc(3)], 4, 2)], "duplicate document"),
        ([response([doc(1), doc(1, suffix=1)], 3, 0), response([], 3, 2)], "empty page"),
        ([response([doc(1)], 1, 0, exact=False)], "not exact"),
        ([response([doc(1)], 2, 5)], "unexpected offset"),
        ([response([doc(1), doc(2), doc(3)], 3, 0)], "more records than requested"),
        ([response([doc(1), doc(2)], 1, 0)], "more records than reported"),
        ([response([doc(1)], 0, 0)], "empty inventory"),
    ],
)
def test_inconsistent_pagination_is_rejected(responses, match):
    fail(responses, RuntimeError, match, page_size=2)


def test_incomplete_inventory_within_page_limit_is_rejected(capsys):
    docs = verified_inventory()
    _, session = fail(paged(docs), RuntimeError, r"incomplete: received 80/93", max_pages=4)
    assert session.get.call_count == 4
    assert "status=failed pages=4 raw_records=80 records=80 total=93" in capsys.readouterr().out


def test_same_requisition_across_cities_produces_one_job_with_all_locations():
    docs = group(144911, ["Gurgaon", "Noida", "Bengaluru", "Mumbai"])
    jobs, _ = fetch([response(docs, 4, 0)])

    assert len(jobs) == 1
    job = jobs[0]
    assert job.id == "2026-144911"
    assert job.location == (
        "Gurgaon, Haryana, India | Noida, Uttar Pradesh, India | "
        "Bengaluru, Karnataka, India | Mumbai, Maharashtra, India"
    )
    assert str(job.url) == (
        "https://careers.publicissapient.com/job-details/"
        "2026-144911-senior-associate-software-engineer-gurgaon"
    )


@pytest.mark.parametrize("target", ["Bengaluru", "Mumbai"])
def test_target_city_eligibility_is_kept_when_another_city_is_primary(target):
    docs = group(144968, ["Gurgaon", "Noida", "Pune", target])
    other = group(144904, ["Gurgaon", "Noida", "Hyderabad"])
    jobs = PublicisSapientAdapter().parse(docs + other, company())
    job_filter = JobFilter()

    included = {job.id: job_filter.should_include(job) for job in jobs}
    assert included == {"2026-144968": True, "2026-144904": False}


def test_canonical_identity_is_stable_across_record_order():
    docs = group(150989, ["Bengaluru", "Gurgaon", "Hyderabad", "Mumbai"])
    baseline = PublicisSapientAdapter().parse(docs, company())
    for seed in range(5):
        shuffled = docs[:]
        random.Random(seed).shuffle(shuffled)
        assert PublicisSapientAdapter().parse(shuffled, company()) == baseline
    assert str(baseline[0].url).endswith("/job-details/2026-150989-senior-associate-software-engineer-bengaluru")


def test_missing_primary_uses_lowest_document_id_deterministically():
    docs = group(144915, ["Bengaluru", "Gurgaon", "Noida"])[1:]
    jobs = PublicisSapientAdapter().parse(docs[::-1], company())
    assert jobs[0].id == "2026-144915"
    assert str(jobs[0].url).endswith("2026-144915-1000001-senior-associate-software-engineer-gurgaon")
    assert jobs[0].location.startswith("Gurgaon")


def test_url_identity_under_title_and_city_changes():
    base = group(166103, ["Gurgaon", "Bengaluru", "Pune"])
    [original] = PublicisSapientAdapter().parse(base, company())

    secondary_changed = [dict(item) for item in base]
    secondary_changed[2].update(group(166103, ["Gurgaon", "Bengaluru", "Mumbai"])[2])
    [moved] = PublicisSapientAdapter().parse(secondary_changed, company())
    assert moved.url == original.url
    assert "Mumbai" in moved.location and "Pune" not in moved.location

    # The official slug embeds the title and primary city, so the
    # adapter forwards the site's new URL rather than inventing one.
    renamed = [dict(item) for item in base]
    renamed[0]["name"] = "Senior Associate Software Engineer L2"
    renamed[0]["jobDetailUrl"] = "/job-details/2026-166103-senior-associate-software-engineer-l2-gurgaon"
    [retitled] = PublicisSapientAdapter().parse(renamed, company())
    assert retitled.id == original.id
    assert str(retitled.url).endswith(renamed[0]["jobDetailUrl"])
    assert retitled.url != original.url


def test_absolute_official_detail_url_is_preserved():
    record = doc(1)
    record["jobDetailUrl"] = "https://careers.publicissapient.com" + record["jobDetailUrl"]
    assert str(PublicisSapientAdapter().parse([record], company())[0].url) == record["jobDetailUrl"]


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("id", None, "document ID or jobId"),
        ("jobId", "", "document ID or jobId"),
        ("id", "2026-999", "does not belong"),
        ("name", " ", "title"),
        ("jobDetailUrl", None, "job URL"),
        ("jobDetailUrl", "https://sapient-publicisgroupe.icims.com/jobs/1/job/login", "job URL"),
        ("jobDetailUrl", "/job-details/", "job URL"),
        ("jobDetailUrl", "/job-details/a/../b", "job URL"),
        ("jobDetailUrl", "/job-details/a?x=1", "job URL"),
    ],
)
def test_malformed_records_are_rejected(field, value, match):
    record = doc(1)
    record[field] = value
    with pytest.raises(ValueError, match=match):
        PublicisSapientAdapter().parse([record], company())


def test_malformed_record_during_fetch_fails_company():
    fail([response([{"jobId": "2026-1"}], 1, 0)], RuntimeError, "document ID")


@pytest.mark.parametrize(("status", "category"), [(429, "rate_limit"), (503, "server_error")])
def test_temporary_http_failures_are_classified(status, category, capsys):
    error = response([], 0, 0, status=status)
    error.headers = {"Retry-After": "7"}
    raised, _ = fail([error], ProviderTemporaryError, f"HTTP {status}")
    assert raised.value.category == category
    assert raised.value.retry_after_seconds == 7
    assert "status=failed pages=1 raw_records=0 records=0 total=None" in capsys.readouterr().out


def test_unexpected_endpoint_is_rejected():
    with pytest.raises(ValueError, match="Unexpected Publicis Sapient API endpoint"):
        PublicisSapientAdapter().fetch_jobs(company(api_url="https://example.com/search"))


def test_timeout_after_partial_inventory_returns_no_jobs(tmp_path):
    docs = verified_inventory()
    session = Mock()
    session.get.side_effect = paged(docs)[:2] + [requests.Timeout("slow")]
    recovery = RecoveryStore(tmp_path / "recovery.json")

    with patch("src.providers.publicis_sapient.requests.Session") as factory:
        factory.return_value.__enter__.return_value = session
        result = _run_company(company(), PublicisSapientAdapter(), JobFilter(), recovery, {})

    assert not result.success
    assert result.coverage_status == "failed"
    assert "slow" in result.error
    assert result.matching == []
    assert result.jobs_fetched == 0


def test_multi_location_job_is_notified_once_and_not_repeated(tmp_path):
    docs = group(166102, ["Gurgaon", "Bengaluru", "Mumbai", "Pune"])
    store = SeenStore(tmp_path / "seen.json")
    notifier = Mock()

    for _ in range(2):
        jobs, _ = fetch([response(docs, len(docs), 0)])
        matching = [job for job in jobs if JobFilter().should_include(job)]
        _send_notifications(store, notifier, store.filter_new(matching), 25, _settings())

    assert notifier.send_message.call_count == 1
    message = notifier.send_message.call_args.args[0]
    assert message.count("2026-166102-senior-associate-software-engineer-gurgaon") == 1
    assert json.loads((tmp_path / "seen.json").read_text(encoding="utf-8")) == {
        "seen": [
            "https://careers.publicissapient.com/job-details/"
            "2026-166102-senior-associate-software-engineer-gurgaon"
        ]
    }


def test_registry_entry_uses_publicis_sapient_adapter():
    registry = CompanyRegistry.model_validate_json(
        (ROOT / "config" / "companies.json").read_text(encoding="utf-8")
    )
    entry = next(c for c in registry.companies if c.id == "publicissapient")

    assert entry.enabled is True
    assert entry.provider.type == ProviderType.PUBLICIS_SAPIENT
    assert entry.provider.config.api_url == API
    assert entry.provider.config.search_location == "India"
    assert entry.provider.config.page_size == 20
    assert entry.provider.config.max_pages == 10
    assert isinstance(_ADAPTERS[entry.provider.type], PublicisSapientAdapter)
