from types import SimpleNamespace
from unittest.mock import patch

from models import Job
from models.company import ProviderType
from src.filters import JobFilter
from src.main import (
    _print_company_stats,
    _record_selection_diagnostics,
    _run_company,
)
from src.run_result import CompanyRunResult
from src.store import SeenStore


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


def test_run_selection_summary_distinguishes_global_and_company_counts(tmp_path, capsys):
    from src.main import _print_selection_summary

    seen = _job("Seen Engineer", "Mumbai")
    first = _job("First Engineer", "Mumbai")
    second = _job("Second Engineer", "Mumbai")
    ignored = _job("Failed Engineer", "Mumbai")
    store = SeenStore(tmp_path / "seen.json")
    store.mark_seen([seen])
    state_before = (tmp_path / "seen.json").read_bytes()
    results = [
        CompanyRunResult("a", "A", "IBM", matching=[seen, first, first]),
        CompanyRunResult("b", "B", "HCLTech", matching=[seen, first, second]),
        CompanyRunResult("failed", "Failed", "Other", success=False, matching=[ignored]),
    ]
    all_matching = [job for result in results if result.success for job in result.matching]
    new_jobs = store.filter_new(all_matching)
    _record_selection_diagnostics(results, store, new_jobs)

    _print_selection_summary(results, all_matching, store)

    assert new_jobs == [first, second]
    assert (tmp_path / "seen.json").read_bytes() == state_before
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1
    assert "[SELECTION]" in lines[0]
    assert "matching_records=6 " in lines[0]
    assert "unique_matching_urls=3 " in lines[0]
    assert "company_unique_matching_urls=5 " in lines[0]
    assert "seen_urls=1 " in lines[0]
    assert "company_seen_urls=2 " in lines[0]
    assert "new_unique_urls=2 " in lines[0]
    assert "within_company_duplicates=1 " in lines[0]
    assert "cross_company_duplicate_urls=2 " in lines[0]
    assert "cross_company_duplicates_suppressed=1" in lines[0]
