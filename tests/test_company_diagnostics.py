from types import SimpleNamespace
from unittest.mock import patch

from models import Job
from models.company import ProviderType
from src.filters import JobFilter
from src.main import (
    _print_company_stats,
    _run_company,
)


def _job(title: str, location: str) -> Job:
    return Job(
        id=title,
        title=title,
        company="Acme",
        location=location,
        url=f"https://example.com/{title.replace(' ', '-')}",
    )


def test_zero_match_company_prints_counts_and_at_most_two_samples(capsys):
    jobs = [
        _job("Engineer II", "Bengaluru"),
        _job("Software Engineer Intern", "Bengaluru"),
        _job("Backend Engineer", "Pune, India"),
        _job("Lead Software Engineer", "Mumbai"),
    ]
    diagnostics = JobFilter().diagnose(jobs, sample_limit=2)

    _print_company_stats(
        SimpleNamespace(name="Acme"),
        jobs_fetched=len(jobs),
        direct_count=0,
        promoted_count=0,
        total_matching=0,
        filter_diagnostics=diagnostics,
    )

    output = capsys.readouterr().out
    assert (
        "[FILTER] rejected include=1 excluded=1 "
        "location=1 seniority=1"
    ) in output
    assert output.count("[FILTER] sample ") == 2
    assert "Engineer II | Bengaluru" in output
    assert "Software Engineer Intern | Bengaluru" in output


def test_company_stats_without_diagnostics_do_not_print_filter_output(capsys):
    _print_company_stats(
        SimpleNamespace(name="Acme"),
        jobs_fetched=0,
        direct_count=0,
        promoted_count=0,
        total_matching=0,
    )

    assert "[FILTER]" not in capsys.readouterr().out


def test_run_company_attaches_diagnostics_only_after_successful_fetch():
    company = SimpleNamespace(
        id="acme",
        name="Acme",
        provider=SimpleNamespace(type=ProviderType.WORKDAY),
    )
    rejected_job = _job("Backend Engineer", "Remote - Indiana, USA")

    with patch(
        "src.main._fetch_jobs_with_recovery",
        return_value=([rejected_job], None),
    ):
        result = _run_company(
            company,
            adapter=None,
            job_filter=JobFilter(),
            recovery_store=None,
            recovery_settings={},
        )

    assert result.success
    assert result.filter_diagnostics is not None
    assert result.filter_diagnostics.location == 1

    with patch(
        "src.main._fetch_jobs_with_recovery",
        return_value=(None, None),
    ):
        failed_result = _run_company(
            company,
            adapter=None,
            job_filter=JobFilter(),
            recovery_store=None,
            recovery_settings={},
        )

    assert not failed_result.success
    assert failed_result.filter_diagnostics is None
