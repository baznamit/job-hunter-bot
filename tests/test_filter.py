import pytest

from models import Job
from src.filters import JobFilter


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
