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

def test_search_jobs_outranks_generic_career_links():
    html = """
    <a href="/careers/engineering">Careers in Engineering</a>
    <a href="/careers/design">Careers in Design</a>
    <a href="/careers/students">Student Careers</a>
    <a href="/careers/benefits">Career Benefits</a>
    <a href="/careers/locations">Career Locations</a>

    <a href="/careers/search-jobs">Search Jobs</a>
    """

    links = extract_career_links(
        html,
        "https://example.com/careers",
        limit=5,
    )

    assert (
        "https://example.com/careers/search-jobs"
        in links
    )

    assert links[0] == (
        "https://example.com/careers/search-jobs"
    )


def test_excludes_current_page():
    html = """
    <a href="/careers">Careers</a>
    <a href="/careers/search-jobs">Search Jobs</a>
    """

    links = extract_career_links(
        html,
        "https://example.com/careers",
    )

    assert "https://example.com/careers" not in links

    assert (
        "https://example.com/careers/search-jobs"
        in links
    )


def test_excludes_localised_copies_of_career_page():
    html = """
    <a href="/de/company/careers">Karriere</a>
    <a href="/fr/company/careers">Carrières</a>
    <a href="/zh/company/careers">Careers</a>

    <a href="/company/careers/search-jobs">
        Search Jobs
    </a>
    """

    links = extract_career_links(
        html,
        "https://example.com/company/careers",
    )

    assert (
        "https://example.com/de/company/careers"
        not in links
    )

    assert (
        "https://example.com/fr/company/careers"
        not in links
    )

    assert (
        "https://example.com/zh/company/careers"
        not in links
    )

    assert links[0] == (
        "https://example.com/company/careers/search-jobs"
    )


def test_external_job_platform_is_ranked_highly():
    html = """
    <a href="/careers/culture">Careers and Culture</a>

    <a href="https://example.keka.com/careers">
        View Open Positions
    </a>
    """

    links = extract_career_links(
        html,
        "https://example.com/careers",
    )

    assert links[0] == (
        "https://example.keka.com/careers"
    )