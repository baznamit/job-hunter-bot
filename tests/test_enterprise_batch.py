from types import SimpleNamespace
from unittest.mock import patch

from research.company_probe import (
    _enterprise_page_evidence,
    _enterprise_validate_existing,
    _kpmg_oracle_evidence,
    _mastek_listing_evidence,
)
from research.loader import load_registry


def test_detects_successfactors_job_link():
    html = """
    <a href="/job/Pune/Java-Developer/12345">
      Java Developer
    </a>
    """

    result = _enterprise_page_evidence(
        html,
        "https://careers.mastek.com/search/",
    )

    assert len(result["job_links"]) == 1
    assert any(
        "/job/" in url
        for url in result["job_links"]
    )


def test_detects_oracle_site_path_without_guessing_number():
    html = """
    <a href="https://example.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_3">
      KPMG Global Services
    </a>
    """

    result = _enterprise_page_evidence(
        html,
        "https://kpmg.com/in/en/careers.html",
    )

    assert (
        "example.fa.em2.oraclecloud.com",
        "CX_3",
    ) in result["oracle_sites"]


def test_does_not_accept_unrelated_job_links():
    html = """
    <a href="https://example.com/job/123">
      Java Developer
    </a>
    <a href="/about-us">
      Software Engineer
    </a>
    """

    result = _enterprise_page_evidence(
        html,
        "https://careers.mastek.com/",
    )

    # This extractor is evidence-only, not a trusted
    # company-specific job parser.
    assert len(result["job_links"]) == 1


def test_existing_company_validation_uses_registry():
    company = SimpleNamespace(
        id="ltmindtree",
        provider=SimpleNamespace(
            type=SimpleNamespace(
                value="successfactors"
            )
        ),
    )

    company.model_copy = lambda deep: company

    registry = SimpleNamespace(
        companies=[company]
    )

    job = SimpleNamespace(
        id="123",
        title="Java Backend Developer",
        location="Mumbai, India",
        url="https://careers.ltm.com/job/123",
    )

    with patch(
        "src.providers.successfactors."
        "SuccessFactorsAdapter.fetch_jobs",
        return_value=[job],
    ) as fetch:
        assert _enterprise_validate_existing(
            "ltmindtree", registry
        )

    fetch.assert_called_once()


def test_ltimindtree_already_registered():
    registry = load_registry()

    matches = [
        company
        for company in registry.companies
        if company.id == "ltmindtree"
    ]

    assert len(matches) == 1

    company = matches[0]

    assert company.enabled is True
    assert company.provider.type.value == "successfactors"
    assert company.provider.config.base_url == (
        "https://careers.ltm.com"
    )


def test_mastek_extracts_requisition_ids():
    html = """
    <a href="/job/Mumbai-Java-Developer/123456/">
      Java Developer
    </a>
    <a href="/job/Pune-Backend-Engineer/789012/">
      Backend Engineer
    </a>
    """

    result = _mastek_listing_evidence(
        html,
        "https://careers.mastek.com/search/",
    )

    assert set(result["jobs"]) == {
        "123456",
        "789012",
    }


def test_mastek_detects_observed_path_pagination():
    html = """
    <a href="/search/12/">2</a>
    <a href="/search/24/">3</a>
    """

    result = _mastek_listing_evidence(
        html,
        "https://careers.mastek.com/search/",
    )

    assert (
        "https://careers.mastek.com/search/12/"
        in result["pagination"]
    )


def test_mastek_detects_observed_query_pagination():
    html = """
    <a href="/search/?startrow=12">Next</a>
    """

    result = _mastek_listing_evidence(
        html,
        "https://careers.mastek.com/search/",
    )

    assert (
        "https://careers.mastek.com/search/?startrow=12"
        in result["pagination"]
    )


def test_kpmg_detects_explicit_site_number_candidate():
    html = """
    <script>
      window.publicConfig = {
        "siteNumber": "1234"
      };
    </script>
    """

    result = _kpmg_oracle_evidence(html)

    assert result["site_number_candidates"] == [
        "1234"
    ]


def test_kpmg_does_not_infer_number_from_site_path():
    html = """
    <a href="/hcmUI/CandidateExperience/en/sites/CX_3001">
      KPMG Delivery Network
    </a>
    """

    result = _kpmg_oracle_evidence(html)

    assert result["site_number_candidates"] == []


def test_kpmg_handles_no_embedded_configuration():
    result = _kpmg_oracle_evidence(
        "<html><body>Careers</body></html>"
    )

    assert result["site_number_candidates"] == []
    assert result["script_count"] == 0
