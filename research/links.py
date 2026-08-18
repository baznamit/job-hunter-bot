from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse, urlunparse


# Strong signals that a link probably leads to an actual job listing/search.
_HIGH_VALUE_PHRASES = (
    "search jobs",
    "search-jobs",
    "find jobs",
    "find-jobs",
    "view jobs",
    "view-jobs",
    "browse jobs",
    "browse-jobs",
    "all jobs",
    "all-jobs",
    "open positions",
    "open-positions",
    "job openings",
    "job-openings",
    "current openings",
    "current-openings",
    "job search",
    "job-search",
    "vacancies",
)

# Useful, but weaker, career-related signals.
_MEDIUM_VALUE_PHRASES = (
    "jobs",
    "/jobs",
    "openings",
    "opportunities",
    "positions",
    "join us",
    "join-us",
    "joinus",
)

# Generic career links are useful only when stronger links don't exist.
_LOW_VALUE_PHRASES = (
    "career",
    "careers",
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


def _normalise_url(url: str) -> str:
    """
    Normalise a URL for duplicate comparison.

    Fragments are irrelevant for ATS discovery, so remove them.
    Trailing slashes are also normalised.
    """

    parsed = urlparse(url)

    path = parsed.path.rstrip("/") or "/"

    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            parsed.params,
            parsed.query,
            "",
        )
    )


def _is_same_page(candidate: str, base_url: str) -> bool:
    """
    Return True when candidate resolves to the page we're already on.
    """

    return _normalise_url(candidate) == _normalise_url(base_url)


def _is_localised_career_copy(
    candidate: str,
    base_url: str,
) -> bool:
    """
    Detect translated copies of the current careers page.

    Example:

        base:
            /company/careers

        duplicates:
            /de/company/careers
            /fr/company/careers
            /zh/company/careers

    These pages add little discovery value and previously consumed
    Atlassian's entire five-link crawl budget.
    """

    candidate_parsed = urlparse(candidate)
    base_parsed = urlparse(base_url)

    if candidate_parsed.netloc.lower() != base_parsed.netloc.lower():
        return False

    base_parts = [
        part
        for part in base_parsed.path.strip("/").split("/")
        if part
    ]

    candidate_parts = [
        part
        for part in candidate_parsed.path.strip("/").split("/")
        if part
    ]

    if len(candidate_parts) != len(base_parts) + 1:
        return False

    if candidate_parts[1:] != base_parts:
        return False

    locale = candidate_parts[0].lower()

    # Covers common language/locale prefixes such as:
    # /de/, /fr/, /zh/, /en-us/, /en-gb/
    if len(locale) == 2 and locale.isalpha():
        return True

    if (
        len(locale) == 5
        and locale[2] == "-"
        and locale[:2].isalpha()
        and locale[3:].isalpha()
    ):
        return True

    return False

def _is_social_or_share_link(url: str) -> bool:
    host = urlparse(url).netloc.lower()

    social_hosts = (
        "facebook.com",
        "www.facebook.com",
        "linkedin.com",
        "www.linkedin.com",
        "twitter.com",
        "www.twitter.com",
        "x.com",
        "www.x.com",
        "instagram.com",
        "www.instagram.com",
    )

    return host in social_hosts

def _score_link(
    href: str,
    text: str,
    absolute: str,
    base_url: str,
) -> int:
    """
    Score how likely a link is to lead toward actual job listings.
    """

    haystack = f"{href} {text}".lower()
    score = 0

    if any(
        phrase in haystack
        for phrase in _HIGH_VALUE_PHRASES
    ):
        score += 100

    if any(
        phrase in haystack
        for phrase in _MEDIUM_VALUE_PHRASES
    ):
        score += 50

    if any(
        phrase in haystack
        for phrase in _LOW_VALUE_PHRASES
    ):
        score += 10

    candidate_host = urlparse(absolute).netloc.lower()
    base_host = urlparse(base_url).netloc.lower()

    # External job/career domains are particularly valuable. Jupiter's
    # jupiter.keka.com link is an example of why this matters.
    if candidate_host and candidate_host != base_host:
        if any(
            word in candidate_host
            for word in (
                "job",
                "jobs",
                "career",
                "careers",
                "greenhouse",
                "lever",
                "ashby",
                "workday",
                "keka",
            )
        ):
            score += 80
        else:
            score += 20

    path = urlparse(absolute).path.lower()

    if "/jobs" in path:
        score += 40

    if "search" in path:
        score += 30

    return score


def extract_career_links(
    html: str,
    base_url: str,
    limit: int = 5,
) -> list[str]:
    """
    Extract and rank likely job/career links.

    Links are scored by relevance before the crawl limit is applied.
    This prevents generic career pages or translated copies from
    consuming all available discovery slots.
    """

    parser = _LinkParser()
    parser.feed(html)

    candidates: dict[str, tuple[int, int, str]] = {}

    for index, (href, text) in enumerate(parser.links):
        if not href:
            continue

        absolute = urljoin(base_url, href)

        if _is_social_or_share_link(absolute):
            continue

        if not absolute.startswith(("http://", "https://")):
            continue

        if _is_same_page(absolute, base_url):
            continue

        if _is_localised_career_copy(
            absolute,
            base_url,
        ):
            continue

        score = _score_link(
            href=href,
            text=text,
            absolute=absolute,
            base_url=base_url,
        )

        # Ignore links with no career/job relevance at all.
        if score <= 0:
            continue

        normalised = _normalise_url(absolute)

        existing = candidates.get(normalised)

        # Keep the strongest occurrence when the same URL appears
        # multiple times on the page.
        if existing is None or score > existing[0]:
            candidates[normalised] = (
                score,
                index,
                absolute,
            )

    ranked = sorted(
        candidates.values(),
        key=lambda item: (
            -item[0],
            item[1],
        ),
    )

    return [
        absolute
        for _, _, absolute in ranked[:limit]
    ]