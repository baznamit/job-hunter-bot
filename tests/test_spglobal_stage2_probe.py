from bs4 import BeautifulSoup

from research.spglobal_stage2_probe import (
    INDIA_RE,
    ROLE_RE,
    extract_jsonld,
    unique_values,
)


def test_unique_values_preserves_order():
    assert unique_values(["a", "b", "a", "c"]) == [
        "a",
        "b",
        "c",
    ]


def test_relevant_java_roles():
    assert ROLE_RE.search("Java Software Engineer II")
    assert ROLE_RE.search("Spring Boot Developer")
    assert ROLE_RE.search("Full Stack Engineer")
    assert ROLE_RE.search("Backend Developer")

    assert not ROLE_RE.search("Marketing Manager")


def test_india_locations():
    assert INDIA_RE.search("Mumbai, India")
    assert INDIA_RE.search("Bengaluru, Karnataka")
    assert INDIA_RE.search("Hyderabad, Telangana")

    assert not INDIA_RE.search("New York, USA")


def test_extract_jsonld():
    soup = BeautifulSoup(
        """
        <script type="application/ld+json">
        {
          "@type": "JobPosting",
          "title": "Java Software Engineer II"
        }
        </script>
        """,
        "html.parser",
    )

    objects = extract_jsonld(soup)

    assert len(objects) == 1
    assert objects[0]["@type"] == "JobPosting"
    assert objects[0]["title"] == "Java Software Engineer II"


def test_invalid_jsonld_is_ignored():
    soup = BeautifulSoup(
        """
        <script type="application/ld+json">
        invalid-json
        </script>
        """,
        "html.parser",
    )

    assert extract_jsonld(soup) == []
