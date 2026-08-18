import pytest

from models import Job
from src.filters import JobFilter, RejectionReason


def _job(title: str, location: str) -> Job:
    return Job(
        id="1",
        title=title,
        company="Acme",
        location=location,
        url="https://example.com/jobs/1",
    )


@pytest.fixture
def f() -> JobFilter:
    return JobFilter()


# ── include keyword ───────────────────────────────────────────────────────────

def test_includes_backend_engineer(f):
    assert f.should_include(_job("Backend Engineer", "Bangalore, India"))


def test_includes_java_developer(f):
    assert f.should_include(_job("Java Developer", "Bangalore, India"))


def test_includes_software_engineer(f):
    assert f.should_include(_job("Software Engineer", "Bengaluru"))


def test_excludes_no_keyword_match(f):
    assert not f.should_include(_job("Product Designer", "Bangalore"))


# ── exclude keyword ───────────────────────────────────────────────────────────

def test_excludes_intern(f):
    assert not f.should_include(_job("Software Engineer Intern", "Bangalore"))


def test_excludes_qa_engineer(f):
    assert not f.should_include(_job("Backend QA Engineer", "Pune"))


def test_excludes_ml_engineer(f):
    assert not f.should_include(_job("Backend ML Engineer", "Bangalore"))


# ── location ──────────────────────────────────────────────────────────────────

def test_includes_bangalore_india(f):
    assert f.should_include(_job("Backend Engineer", "Bangalore, India"))


def test_includes_bengaluru(f):
    assert f.should_include(_job("Platform Engineer", "Bengaluru, Karnataka, India"))


def test_includes_mumbai(f):
    assert f.should_include(_job("Software Engineer", "Mumbai"))


def test_includes_mumbai_india(f):
    assert f.should_include(_job("Software Engineer", "Mumbai, India"))


def test_includes_remote_bangalore(f):
    # "Remote - Bangalore" is an India-based remote role and should match.
    assert f.should_include(_job("Backend Engineer", "Remote - Bangalore"))


def test_includes_hybrid_bengaluru(f):
    assert f.should_include(_job("Backend Engineer", "Hybrid - Bengaluru"))


def test_excludes_generic_remote(f):
    # Standalone "Remote" has no city — could be anywhere, exclude it.
    assert not f.should_include(_job("Backend Engineer", "Remote"))


def test_excludes_remote_canada(f):
    assert not f.should_include(_job("Backend Engineer", "Remote - Canada"))


def test_excludes_remote_brazil(f):
    assert not f.should_include(_job("Software Engineer", "Remote - Brazil"))


def test_excludes_us_location(f):
    assert not f.should_include(_job("Software Engineer", "San Francisco, CA"))


def test_excludes_new_york(f):
    assert not f.should_include(_job("Backend Engineer", "New York, NY"))


# ── seniority ─────────────────────────────────────────────────────────────────

def test_excludes_senior(f):
    assert not f.should_include(_job("Senior Software Engineer", "Bangalore"))


def test_excludes_lead(f):
    assert not f.should_include(_job("Lead Backend Engineer", "Pune"))


def test_excludes_vp(f):
    assert not f.should_include(_job("VP of Engineering", "India"))

def test_diagnostic_reports_missing_include(f):
    job = _job(
        "Engineer II",
        "Bengaluru",
    )

    result = f.evaluate(job)

    assert not result.included
    assert result.reason == RejectionReason.INCLUDE_KEYWORD


def test_diagnostic_reports_excluded_keyword(f):
    job = _job(
        "Software Engineer Android",
        "Bengaluru",
    )

    result = f.evaluate(job)

    assert not result.included
    assert result.reason == RejectionReason.EXCLUDED_KEYWORD


def test_diagnostic_reports_location(f):
    job = _job(
        "Software Engineer",
        "India",
    )

    result = f.evaluate(job)

    assert not result.included
    assert result.reason == RejectionReason.LOCATION


def test_diagnostic_reports_seniority(f):
    job = _job(
        "Senior Software Engineer",
        "Bengaluru",
    )

    result = f.evaluate(job)

    assert not result.included
    assert result.reason == RejectionReason.SENIORITY


def test_engineer_ii_is_useful_near_miss(f):
    job = _job(
        "Engineer II",
        "Bengaluru",
    )

    assert f.is_useful_near_miss(
        job,
        RejectionReason.INCLUDE_KEYWORD,
    )


def test_senior_software_engineer_is_useful_near_miss(f):
    job = _job(
        "Senior Software Engineer",
        "Mumbai",
    )

    assert f.is_useful_near_miss(
        job,
        RejectionReason.SENIORITY,
    )


def test_marketing_role_is_not_useful_near_miss(f):
    job = _job(
        "Marketing Manager",
        "Bengaluru",
    )

    assert not f.is_useful_near_miss(
        job,
        RejectionReason.INCLUDE_KEYWORD,
    )


def test_diagnostic_counts_add_up(f):
    jobs = [
        _job("Software Engineer", "Bengaluru"),
        _job("Engineer II", "Bengaluru"),
        _job("Software Engineer Android", "Bengaluru"),
        _job("Software Engineer", "India"),
        _job("Senior Software Engineer", "Mumbai"),
    ]

    diagnostics = f.diagnose(jobs)

    assert diagnostics.total == 5
    assert diagnostics.matched == 1
    assert diagnostics.include_keyword == 1
    assert diagnostics.excluded_keyword == 1
    assert diagnostics.location == 1
    assert diagnostics.seniority == 1

    assert (
        diagnostics.matched
        + diagnostics.include_keyword
        + diagnostics.excluded_keyword
        + diagnostics.location
        + diagnostics.seniority
        == diagnostics.total
    )