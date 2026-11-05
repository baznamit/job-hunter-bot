from research.company_probe import (
    inspect_company_page_structure,
)


def test_aspnet_form_and_hidden_names(capsys):
    html = """
    <html>
      <form method="post"
            action="/CurrentOpportunity.aspx?token=PRIVATE_QUERY">
        <input type="hidden"
               name="__VIEWSTATE"
               value="PRIVATE_SESSION_DATA">
        <input type="hidden"
               name="__EVENTVALIDATION"
               value="PRIVATE_EVENT_DATA">
        <input type="text" name="txtSkill">
        <input type="submit" name="btnSearch">
      </form>
    </html>
    """

    result = inspect_company_page_structure(
        "TECHMAHINDRA",
        html,
        "https://careers.techmahindra.com/",
    )

    assert len(result["forms"]) == 1

    form = result["forms"][0]

    assert form["method"] == "POST"
    assert form["action"].endswith(
        "/CurrentOpportunity.aspx"
    )

    assert "__VIEWSTATE" in form["hidden_names"]
    assert "__EVENTVALIDATION" in form["hidden_names"]

    output = capsys.readouterr().out
    assert "PRIVATE_SESSION_DATA" not in output
    assert "PRIVATE_QUERY" not in output


def test_job_table_extraction():
    html = """
    <table id="jobs">
      <tr>
        <th>Job Title</th>
        <th>Experience</th>
        <th>Location</th>
      </tr>
      <tr>
        <td>Java Developer</td>
        <td>3-5 Years</td>
        <td>Mumbai</td>
      </tr>
    </table>
    """

    result = inspect_company_page_structure(
        "TECHMAHINDRA",
        html,
        "https://careers.techmahindra.com/",
    )

    assert result["tables"][0]["headers"] == [
        "Job Title",
        "Experience",
        "Location",
    ]

    assert result["tables"][0]["rows"][0] == [
        "Java Developer",
        "3-5 Years",
        "Mumbai",
    ]


def test_postback_pagination_detected():
    html = """
    <a href="javascript:__doPostBack('JobsGrid','Page$2')">
      2
    </a>
    <a href="javascript:__doPostBack('JobsGrid','Page$Next')">
      Next
    </a>
    """

    result = inspect_company_page_structure(
        "TECHMAHINDRA",
        html,
        "https://careers.techmahindra.com/",
    )

    assert len(result["pagination"]) == 2
    assert "Page$2" in result["pagination"][0]["href"]


def test_crisil_job_reference_extraction():
    html = """
    <div>
      Job Reference: CR12345
      <script src="/static/careers.js?session=SECRET_SCRIPT_TOKEN#top"></script>
    </div>
    """

    result = inspect_company_page_structure(
        "CRISIL",
        html,
        "https://career.crisil.com/crisil/",
    )

    assert "CR12345" in result["job_references"]
    assert result["scripts"] == [
        "https://career.crisil.com/static/careers.js"
    ]


def test_no_private_hidden_values_logged(capsys):
    html = """
    <form>
      <input type="hidden" name="sessionToken"
             value="SECRET_VALUE_123">
    </form>
    """

    inspect_company_page_structure(
        "CRISIL",
        html,
        "https://career.crisil.com/crisil/",
    )

    output = capsys.readouterr().out

    assert "sessionToken" in output
    assert "SECRET_VALUE_123" not in output
