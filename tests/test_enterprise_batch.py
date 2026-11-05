from types import SimpleNamespace
from unittest.mock import patch

from research.company_probe import (
    _enterprise_page_evidence,
    _enterprise_validate_existing,
    _kpmg_oracle_config_structure,
    _kpmg_oracle_evidence,
    _mastek_listing_evidence,
    _mastek_pagination_structure,
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


def test_mastek_detects_pager_control():
    html = """
    <button class="pagination-next"
            data-startrow="12">
        Next
    </button>
    """

    result = _mastek_pagination_structure(html)

    assert len(result["controls"]) == 1
    assert result["controls"][0]["label"] == "Next"
    assert result["markers"]["pagination"] is True


def test_mastek_detects_total_count():
    html = """
    <div>Showing 1-12 of 46</div>
    """

    result = _mastek_pagination_structure(html)

    assert "46" in result["total_candidates"]


def test_mastek_does_not_log_hidden_values():
    html = """
    <form>
      <input type="hidden"
             name="__VIEWSTATE"
             value="PRIVATE_SESSION_TOKEN">
      <button name="nextPage">Next</button>
    </form>
    """

    result = _mastek_pagination_structure(html)

    assert "PRIVATE_SESSION_TOKEN" not in str(result)
    assert result["forms"][0]["controls"][0]["name"] == (
        "__VIEWSTATE"
    )


def test_kpmg_extracts_safe_script_references():
    html = """
    <script src="/hcmUI/config.js?token=secret"></script>
    <script src="https://external.example/tracker.js"></script>
    """

    result = _kpmg_oracle_config_structure(
        html,
        "https://ejgk.fa.em2.oraclecloud.com/"
        "hcmUI/CandidateExperience/en/sites/CX_3",
    )

    assert result["scripts"] == [
        "https://ejgk.fa.em2.oraclecloud.com/hcmUI/config.js"
    ]
    assert "secret" not in str(result)


def test_kpmg_does_not_infer_site_number_from_path():
    html = """
    <script>
      window.location = "/sites/CX_3001";
    </script>
    """

    result = _kpmg_oracle_config_structure(
        html,
        "https://ejgk.fa.em2.oraclecloud.com/"
        "hcmUI/CandidateExperience/en/sites/CX_3001",
    )

    assert result["site_number_candidates"] == []


def test_kpmg_detects_public_config_markers():
    html = """
    <script>
      window.publicConfig = {
        siteNumber: null,
        siteName: "KPMG Global Services"
      };
    </script>
    """

    result = _kpmg_oracle_config_structure(
        html,
        "https://ejgk.fa.em2.oraclecloud.com/"
        "hcmUI/CandidateExperience/en/sites/CX_3",
    )

    assert "siteNumber" in result["inline_markers"]
    assert result["site_number_candidates"] == []
