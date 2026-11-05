from research.loader import load_registry
from src.providers.successfactors import SuccessFactorsAdapter

SELECTOR = (
    '#searchresults tr.data-row '
    'td.colTitle a[href*="/job/"]'
)


def test_new_company_successfactors_configuration():
    registry = load_registry()

    companies = {
        company.id: company
        for company in registry.companies
    }

    assert "deloitte_india" in companies
    assert "wissen_successfactors" in companies

    adapter = SuccessFactorsAdapter()

    deloitte = companies["deloitte_india"]
    wissen = companies["wissen_successfactors"]

    assert deloitte.enabled
    assert wissen.enabled

    assert (
        deloitte.provider.config.job_link_selector
        == SELECTOR
    )

    assert (
        wissen.provider.config.job_link_selector
        == SELECTOR
    )

    assert adapter._listing_url(deloitte, 0) == (
        "https://southasiacareers.deloitte.com/"
        "go/Deloitte-India/718244/?q=&title=Java"
    )

    assert adapter._listing_url(deloitte, 25) == (
        "https://southasiacareers.deloitte.com/"
        "go/Deloitte-India/718244/25/?q=&title=Java"
    )

    assert adapter._listing_url(wissen, 0) == (
        "https://jobs.wissen.com/search/"
    )


def test_existing_wissen_zoho_is_preserved():
    registry = load_registry()

    companies = {
        company.id: company
        for company in registry.companies
    }

    wissen = companies["wissen"]

    assert wissen.enabled
    assert wissen.provider.type.value == "zoho_recruit"
    assert wissen.provider.config.api_url == (
        "https://wissen.zohorecruit.in/"
        "recruit/v2/public/Job_Openings"
    )
