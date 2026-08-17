from html.parser import HTMLParser
from urllib.parse import urljoin


_KEYWORDS = (
    "job",
    "jobs",
    "career",
    "careers",
    "opening",
    "openings",
    "opportunit",
    "position",
    "positions",
    "join-us",
    "joinus",
)


class _LinkParser(HTMLParser):

    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a":
            return

        attrs_dict = dict(attrs)
        self._href = attrs_dict.get("href")
        self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag.lower() != "a" or self._href is None:
            return

        self.links.append(
            (
                self._href,
                " ".join(self._text).strip(),
            )
        )

        self._href = None
        self._text = []


def extract_career_links(
    html: str,
    base_url: str,
    limit: int = 5,
) -> list[str]:
    """
    Extract likely job/career links from a career landing page.
    """

    parser = _LinkParser()
    parser.feed(html)

    results: list[str] = []
    seen: set[str] = set()

    for href, text in parser.links:
        absolute = urljoin(base_url, href)

        haystack = f"{href} {text}".lower()

        if not any(keyword in haystack for keyword in _KEYWORDS):
            continue

        if absolute in seen:
            continue

        if not absolute.startswith(("http://", "https://")):
            continue

        seen.add(absolute)
        results.append(absolute)

        if len(results) >= limit:
            break

    return results