from research.links import extract_career_links


def test_extracts_job_link():
    html = """
    <html>
        <body>
            <a href="/about">About</a>
            <a href="/careers/search-jobs">Search Jobs</a>
        </body>
    </html>
    """

    links = extract_career_links(
        html,
        "https://example.com/careers",
    )

    assert links == [
        "https://example.com/careers/search-jobs"
    ]


def test_detects_external_jobs_link():
    html = """
    <a href="https://jobs.example.com/openings">
        View Open Positions
    </a>
    """

    links = extract_career_links(
        html,
        "https://example.com/careers",
    )

    assert links == [
        "https://jobs.example.com/openings"
    ]


def test_ignores_irrelevant_links():
    html = """
    <a href="/about">About Us</a>
    <a href="/products">Products</a>
    <a href="/contact">Contact</a>
    """

    links = extract_career_links(
        html,
        "https://example.com/careers",
    )

    assert links == []