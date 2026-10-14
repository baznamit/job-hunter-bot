import pytest

from models.company import Company
from src.providers.infosys import InfosysAdapter


def _company():
    return Company.model_validate({
        "id": "infosys",
        "name": "Infosys",
        "category": "Product",
        "priority": 2,
        "career_page": "https://career.infosys.com/jobs",
        "provider": {
            "type": "infosys",
            "status": "verified",
            "config": {
                "source_id": "1,21",
            },
        },
    })


def _sample(
    reference="INFSYS-EXTERNAL-255274",
    location="BANGALORE",
):
    return {
        "referenceCode": reference,
        "postingTitle": "Application Security",
        "location": location,
        "createdOn": "2026-10-14T11:08:54.685",
        "unit": "Global Delivery",
        "sourceId": 1,
    }


def test_parse_job():
    jobs = InfosysAdapter().parse(
        [_sample()],
        _company(),
    )

    assert len(jobs) == 1
    assert jobs[0].id == "INFSYS-EXTERNAL-255274"
    assert jobs[0].title == "Application Security"
    assert jobs[0].location == "BANGALORE"
    assert jobs[0].department == "Global Delivery"
    assert jobs[0].posted_at.year == 2026

    assert str(jobs[0].url) == (
        "https://career.infosys.com/jobdesc"
        "?jobReferenceCode=INFSYS-EXTERNAL-255274"
    )


def test_location_whitespace():
    jobs = InfosysAdapter().parse(
        [_sample(location="PUNE          ")],
        _company(),
    )

    assert jobs[0].location == "PUNE"


def test_navi_mumbai():
    jobs = InfosysAdapter().parse(
        [_sample(location="NAVI MUMBAI(MA)")],
        _company(),
    )

    assert jobs[0].location == "NAVI MUMBAI(MA)"


def test_duplicate_reference():
    item = _sample()

    jobs = InfosysAdapter().parse(
        [item, item],
        _company(),
    )

    assert len(jobs) == 1


def test_missing_reference_fails():
    item = _sample()
    item.pop("referenceCode")

    with pytest.raises(ValueError):
        InfosysAdapter().parse(
            [item],
            _company(),
        )


def test_invalid_api_base():
    with pytest.raises(ValueError):
        InfosysAdapter._validate_api_base(
            "https://example.com/api/"
        )


def test_valid_api_base():
    base = InfosysAdapter._validate_api_base(
        "https://intapgateway.infosysapps.com/"
        "careersci/search/intapjbsrch/"
    )

    assert base.endswith(
        "/careersci/search/intapjbsrch/"
    )