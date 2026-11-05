from research.company_probe import (
    _zycus_detail_evidence,
    _zycus_job_links,
    _zycus_nextjs_evidence,
    _zycus_public_jobposting_objects,
    _zycus_structure,
    _zycus_valid_pagination_url,
)


BOARD = "https://zycus.talismatic.com/jobs"


def test_extracts_talismatic_job_links():
    html = """
    <a href="/jobs/JLYSPUJVX">
        Java Tech Lead - GenAI
    </a>
    <a href="/jobs/JLSEKA3V3">
        AI Engineer
    </a>
    """

    jobs = _zycus_job_links(html, BOARD)

    assert len(jobs) == 2
    assert jobs["JLYSPUJVX"]["title"] == (
        "Java Tech Lead - GenAI"
    )
    assert jobs["JLSEKA3V3"]["url"] == (
        "https://zycus.talismatic.com/jobs/JLSEKA3V3"
    )


def test_rejects_unrelated_hosts():
    html = """
    <a href="https://other.talismatic.com/jobs/J123">
        Unrelated
    </a>
    <a href="https://zycus.talismatic.com/jobs/JABC">
        Valid
    </a>
    """

    jobs = _zycus_job_links(html, BOARD)

    assert set(jobs) == {"JABC"}


def test_deduplicates_job_ids():
    html = """
    <a href="/jobs/J123">Java Developer</a>
    <a href="/jobs/J123?source=careers">
        Java Developer
    </a>
    """

    jobs = _zycus_job_links(html, BOARD)

    assert len(jobs) == 1
    assert jobs["J123"]["url"] == (
        "https://zycus.talismatic.com/jobs/J123"
    )


def test_preserves_distinct_pagination_urls():
    html = """
    <a href="/jobs?page=2">2</a>
    <a href="/jobs?page=3">3</a>
    """

    result = _zycus_structure(html, BOARD)

    assert result["pagination_links"] == [
        "https://zycus.talismatic.com/jobs?page=2",
        "https://zycus.talismatic.com/jobs?page=3",
    ]


def test_rejects_unexpected_pagination_parameters():
    assert not _zycus_valid_pagination_url(
        "https://zycus.talismatic.com/jobs?token=secret"
    )

    assert not _zycus_valid_pagination_url(
        "https://zycus.talismatic.com/jobs?page=2&token=x"
    )

    assert not _zycus_valid_pagination_url(
        "https://other.talismatic.com/jobs?page=2"
    )

    assert not _zycus_valid_pagination_url(
        "https://zycus.talismatic.com/jobs?page=0"
    )


def test_accepts_bounded_pagination():
    assert _zycus_valid_pagination_url(
        "https://zycus.talismatic.com/jobs?page=2"
    )

    assert _zycus_valid_pagination_url(
        "https://zycus.talismatic.com/jobs?page=100"
    )

    assert not _zycus_valid_pagination_url(
        "https://zycus.talismatic.com/jobs?page=101"
    )


def test_detects_structured_frontend_markers():
    html = """
    <html>
      <script id="__NEXT_DATA__"
              type="application/json">{}</script>
      <script type="application/ld+json">
        {"@type": "JobPosting"}
      </script>
    </html>
    """

    result = _zycus_structure(html, BOARD)

    assert result["has_next_data"] is True
    assert result["json_ld"][0]["type"] == "JobPosting"


def test_no_credentials_in_canonical_job_url():
    html = """
    <a href="/jobs/J123?session=private">
        Java Engineer
    </a>
    """

    jobs = _zycus_job_links(html, BOARD)

    assert jobs["J123"]["url"] == (
        "https://zycus.talismatic.com/jobs/J123"
    )


def test_zycus_extracts_jobposting_jsonld():
    html = """
    <script type="application/ld+json">
    {
      "@context": "https://schema.org",
      "@type": "JobPosting",
      "title": "Java Backend Engineer",
      "employmentType": "FULL_TIME",
      "jobLocation": {
        "@type": "Place",
        "address": {
          "addressLocality": "Mumbai",
          "addressCountry": "India"
        }
      }
    }
    </script>
    """

    jobs = _zycus_public_jobposting_objects(html)

    assert len(jobs) == 1
    assert jobs[0]["title"] == "Java Backend Engineer"


def test_zycus_extracts_nested_jsonld_graph():
    html = """
    <script type="application/ld+json">
    {
      "@graph": [
        {"@type": "Organization", "name": "Zycus"},
        {"@type": "JobPosting", "title": "Java Developer"}
      ]
    }
    </script>
    """

    jobs = _zycus_public_jobposting_objects(html)

    assert len(jobs) == 1
    assert jobs[0]["title"] == "Java Developer"


def test_zycus_detail_extracts_location_and_canonical():
    html = """
    <html>
      <head>
        <link rel="canonical"
              href="https://zycus.talismatic.com/jobs/J123">
      </head>
      <body>
        <script type="application/ld+json">
        {
          "@type": "JobPosting",
          "title": "Java Full Stack Developer",
          "jobLocation": {
            "address": {
              "addressLocality": "Bengaluru",
              "addressCountry": "India"
            }
          }
        }
        </script>
      </body>
    </html>
    """

    result = _zycus_detail_evidence(html, "J123")

    assert result["title"] == "Java Full Stack Developer"
    assert result["location"] == "Bengaluru, India"
    assert result["canonical"] == (
        "https://zycus.talismatic.com/jobs/J123"
    )


def test_zycus_rejects_unrelated_canonical():
    html = """
    <link rel="canonical"
          href="https://other.example/jobs/J123">
    <h1>Java Developer</h1>
    """

    result = _zycus_detail_evidence(html, "J123")

    assert result["canonical"] == ""
    assert result["title"] == "Java Developer"


def test_zycus_nextjs_evidence_does_not_dump_state():
    html = """
    <script>
      self.__next_f.push([
        1, "jobId PRIVATE_SESSION_VALUE"
      ])
    </script>
    """

    result = _zycus_nextjs_evidence(html)

    assert result["flight_script_count"] == 1
    assert result["flight_job_markers"]["jobId"] == 1
    assert "PRIVATE_SESSION_VALUE" not in str(result)


def test_zycus_handles_invalid_jsonld():
    html = """
    <script type="application/ld+json">
      {invalid json}
    </script>
    """

    assert _zycus_public_jobposting_objects(html) == []
