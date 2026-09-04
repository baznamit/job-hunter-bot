from src.run_result import (
    CompanyRunResult,
)


def test_company_run_result_defaults():
    result = CompanyRunResult(
        company_id="test",
        company_name="Test",
        provider="workday",
    )

    assert result.jobs_fetched == 0
    assert result.matching == []
    assert result.direct_count == 0
    assert result.promoted_count == 0
    assert result.success is True
