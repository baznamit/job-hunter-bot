import html
import re
from urllib.parse import urljoin

import requests

from models import Job
from models.company import Company

from .base import ProviderAdapter


_TIMEOUT = 30
_MAX_PAGES = 100

_DEFAULT_BASE_URL = (
    "https://careers.bankofamerica.com"
)

_JOB_ID_RE = re.compile(
    r"^/en-us/job-detail/(\d+)/",
    flags=re.IGNORECASE,
)


class BankOfAmericaAdapter(ProviderAdapter):
    provider_name = "Bank of America Careers"

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/127.0.0.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,"
                "application/xml;q=0.9,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        }

    def _fetch_html(
        self,
        url: str,
        company: Company,
    ) -> str:
        response = requests.get(
            url,
            headers=self._headers(),
            timeout=_TIMEOUT,
            allow_redirects=True,
        )

        self._check_response(
            response,
            company,
        )

        return response.text

    def _base_url(
        self,
        company: Company,
    ) -> str:
        return (
            company.provider.config.base_url
            or _DEFAULT_BASE_URL
        ).rstrip("/")

    def _clean_text(
        self,
        value: str,
    ) -> str:
        value = re.sub(
            r"<[^>]+>",
            " ",
            value,
        )

        value = html.unescape(
            value
        )

        return re.sub(
            r"\s+",
            " ",
            value,
        ).strip()

    def _keyword_slug(
        self,
        value: str,
    ) -> str:
        value = value.strip().lower()

        value = re.sub(
            r"[^a-z0-9]+",
            "-",
            value,
        )

        return value.strip("-")

    def _search_url(
        self,
        company: Company,
        search_term: str,
    ) -> str:
        base_url = self._base_url(
            company
        )

        slug = self._keyword_slug(
            search_term
        )

        return (
            f"{base_url}/en-us/"
            f"job-search/india/q-{slug}"
        )

    def _extract_total(
        self,
        page_html: str,
    ) -> int | None:
        patterns = (
            r"([\d,]+)\s+relevant\s+jobs",
            r'id=["\']span_results["\'][^>]*>'
            r"\s*([\d,]+)\s*<",
        )

        for pattern in patterns:
            match = re.search(
                pattern,
                page_html,
                flags=re.IGNORECASE,
            )

            if match:
                return int(
                    match.group(1)
                    .replace(",", "")
                )

        return None

    def _extract_jobs(
        self,
        page_html: str,
        company: Company,
    ) -> list[Job]:
        base_url = self._base_url(
            company
        )

        cards = re.findall(
            r'<div\b[^>]*class=["\'][^"\']*'
            r'\bjob-search-tile\b[^"\']*["\'][^>]*>'
            r'(.*?)'
            r'(?=<div\b[^>]*class=["\'][^"\']*'
            r'\bjob-search-tile\b[^"\']*["\']|$)',
            page_html,
            flags=(
                re.IGNORECASE
                | re.DOTALL
            ),
        )

        jobs: list[Job] = []
        seen_ids: set[str] = set()

        for card in cards:
            link_match = re.search(
                r'<a\b[^>]*class=["\'][^"\']*'
                r'job-search-tile__url[^"\']*["\']'
                r'[^>]*href=["\']([^"\']+)["\']'
                r'[^>]*>(.*?)</a>',
                card,
                flags=(
                    re.IGNORECASE
                    | re.DOTALL
                ),
            )

            # Attribute order can change.
            if not link_match:
                anchor_match = re.search(
                    r'<a\b([^>]*)>(.*?)</a>',
                    card,
                    flags=(
                        re.IGNORECASE
                        | re.DOTALL
                    ),
                )

                if not anchor_match:
                    continue

                attrs = anchor_match.group(1)

                if (
                    "job-search-tile__url"
                    not in attrs
                ):
                    continue

                href_match = re.search(
                    r'href=["\']([^"\']+)["\']',
                    attrs,
                    flags=re.IGNORECASE,
                )

                if not href_match:
                    continue

                href = html.unescape(
                    href_match.group(1)
                )

                title = self._clean_text(
                    anchor_match.group(2)
                )

            else:
                href = html.unescape(
                    link_match.group(1)
                )

                title = self._clean_text(
                    link_match.group(2)
                )

            id_match = _JOB_ID_RE.match(
                href
            )

            if not id_match:
                continue

            job_id = id_match.group(1)

            if job_id in seen_ids:
                continue

            location = self._extract_location(
                card
            )

            if not title:
                continue

            seen_ids.add(job_id)

            jobs.append(
                Job(
                    id=job_id,
                    title=title,
                    company=company.name,
                    location=location,
                    url=urljoin(
                        base_url,
                        href,
                    ),
                    department=(
                        self._extract_department(
                            card
                        )
                    ),
                )
            )

        return jobs

    def _extract_location(
        self,
        card: str,
    ) -> str:
        text = self._clean_text(
            card
        )

        match = re.search(
            r"Location\s+(.+?)"
            r"(?=\s+(?:Posted|"
            r"Job Type|"
            r"Career Area|"
            r"Business|$))",
            text,
            flags=re.IGNORECASE,
        )

        if match:
            location = (
                match.group(1)
                .strip(" :-|")
            )

            if location:
                return location

        # Current cards expose the location after
        # an accessibility-only "Location" span.
        match = re.search(
            r'<span[^>]*class=["\'][^"\']*'
            r'ada-hidden[^"\']*["\'][^>]*>'
            r'\s*Location(?:\s*&nbsp;)?\s*'
            r'</span>\s*([^<]+)',
            card,
            flags=(
                re.IGNORECASE
                | re.DOTALL
            ),
        )

        if match:
            location = self._clean_text(
                match.group(1)
            )

            if location:
                return location

        return "Unknown"

    def _extract_department(
        self,
        card: str,
    ) -> str | None:
        text = self._clean_text(
            card
        )

        if "Technology" in text:
            return "Technology"

        return None

    def _extract_next_url(
        self,
        page_html: str,
        current_url: str,
    ) -> str | None:
        anchors = re.findall(
            r'<a\b([^>]*)>(.*?)</a>',
            page_html,
            flags=(
                re.IGNORECASE
                | re.DOTALL
            ),
        )

        for attrs, body in anchors:
            text = self._clean_text(
                body
            ).lower()

            aria_match = re.search(
                r'aria-label=["\']([^"\']+)["\']',
                attrs,
                flags=re.IGNORECASE,
            )

            aria = (
                aria_match.group(1).lower()
                if aria_match
                else ""
            )

            if (
                text != "next"
                and "next" not in aria
            ):
                continue

            href_match = re.search(
                r'href=["\']([^"\']+)["\']',
                attrs,
                flags=re.IGNORECASE,
            )

            if not href_match:
                continue

            href = html.unescape(
                href_match.group(1)
            )

            if not href or href == "#":
                continue

            return urljoin(
                current_url,
                href,
            )

        return None

    def _fetch_search(
        self,
        company: Company,
        search_term: str,
    ) -> list[Job]:
        current_url = self._search_url(
            company,
            search_term,
        )

        jobs: list[Job] = []
        seen_ids: set[str] = set()
        seen_pages: set[str] = set()

        for _ in range(_MAX_PAGES):
            if current_url in seen_pages:
                break

            seen_pages.add(
                current_url
            )

            page_html = self._fetch_html(
                current_url,
                company,
            )

            page_jobs = self._extract_jobs(
                page_html,
                company,
            )

            for job in page_jobs:
                if job.id in seen_ids:
                    continue

                seen_ids.add(job.id)
                jobs.append(job)

            next_url = self._extract_next_url(
                page_html,
                current_url,
            )

            if not next_url:
                break

            current_url = next_url

        else:
            raise RuntimeError(
                f"{company.name}: Bank of America "
                f"pagination exceeded {_MAX_PAGES} pages"
            )

        return jobs

    def _fetch_raw(
        self,
        company: Company,
    ) -> list[Job]:
        search_terms = (
            company.provider.config.search_terms
            or [
                "software developer",
                "software engineer",
                "java",
                "backend",
                "spring boot",
            ]
        )

        jobs: list[Job] = []
        seen_ids: set[str] = set()

        for search_term in search_terms:
            search_jobs = self._fetch_search(
                company,
                search_term,
            )

            for job in search_jobs:
                if job.id in seen_ids:
                    continue

                seen_ids.add(job.id)
                jobs.append(job)

        return jobs

    def parse(
        self,
        raw,
        company: Company,
    ) -> list[Job]:
        return raw

    def validate(
        self,
        company: Company,
    ) -> bool:
        try:
            page_html = self._fetch_html(
                self._search_url(
                    company,
                    "software engineer",
                ),
                company,
            )

            return bool(
                self._extract_jobs(
                    page_html,
                    company,
                )
            )

        except (
            requests.RequestException,
            ValueError,
        ):
            return False