from research.company_probe import (
    extract_techmahindra_jobs,
    _tm_form_payload,
)


HTML = """
<form method="post">
  <input type="hidden"
         name="__VIEWSTATE"
         value="SESSION_STATE">

  <table id="ctl00_ContentPlaceHolder1_DataListRecommended">
    <tr>
      <td>
        <div>
          Java Developer
          Skill Set : Java Spring Boot
          Experience : 3 - 5 Years
          Location : MUMBAI
        </div>

        <input type="hidden"
               name="ctl00$ContentPlaceHolder1$DataListRecommended$ctl00$HdnJobCode"
               value="JOB123">

        <input type="submit"
               name="ctl00$ContentPlaceHolder1$DataListRecommended$ctl00$btn_jobs"
               value="View Job">
      </td>
    </tr>
  </table>
</form>
"""


def test_extracts_job_id_and_fields():
    jobs = extract_techmahindra_jobs(HTML)

    assert len(jobs) == 1

    job = jobs[0]

    assert job["id"] == "JOB123"
    assert "Java Developer" in job["title"]
    assert job["skills"] == "Java Spring Boot"
    assert job["experience"] == "3 - 5 Years"
    assert job["location"] == "MUMBAI"


def test_form_payload_preserves_state():
    payload = _tm_form_payload(
        HTML,
        event_target="JobsPager",
    )

    assert payload["__VIEWSTATE"] == "SESSION_STATE"
    assert payload["__EVENTTARGET"] == "JobsPager"


def test_form_payload_targets_only_selected_job():
    jobs = extract_techmahindra_jobs(HTML)

    payload = _tm_form_payload(
        HTML,
        button_name=jobs[0]["button_name"],
        button_value=jobs[0]["button_value"],
    )

    assert jobs[0]["button_name"] in payload
    assert payload[jobs[0]["button_name"]] == "View Job"


def test_missing_job_table_returns_empty():
    assert extract_techmahindra_jobs(
        "<html><body>No table</body></html>"
    ) == []


def test_duplicate_job_ids_are_removed():
    duplicate = HTML.replace(
        "</tr>",
        """
        <td>
          Another Java Developer
          <input type="hidden"
                 name="ctl00$ContentPlaceHolder1$DataListRecommended$ctl01$HdnJobCode"
                 value="JOB123">
          <input type="submit"
                 name="ctl00$ContentPlaceHolder1$DataListRecommended$ctl01$btn_jobs"
                 value="View Job">
        </td>
        </tr>
        """,
    )

    jobs = extract_techmahindra_jobs(duplicate)

    assert len(jobs) == 1
