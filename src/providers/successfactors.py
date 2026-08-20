import html
import re
from urllib.parse import urljoin

import requests

from models import Job
from models.company import Company

from .base import ProviderAdapter


_TIMEOUT = 30
_MAX_PAGES = 100


class SuccessFactorsAdapter(ProviderAdapter):
    provider_name = "SuccessFactors"

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": (
                "Mozilla/5.0 "
                "(compatible; JobHunterBot/1.0)"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,"
                "application/xml;q=0.9,*/*;q=0.8"
            ),
        }

    def _listing_url(
        self,
        company: Company,
        offset: int,
    ) -> str:
        config = company.provider.config

        if not config.base_url:
            raise ValueError(
                f"{company.name}: SuccessFactors provider "
                "requires base_url"
            )

        if not config.listing_path:
            raise ValueError(
                f"{company.name}: SuccessFactors provider "
                "requires listing_path"
            )

        base_url = config.base_url.rstrip("/")

        listing_path = (
            "/"
            + config.listing_path.strip("/")
            + "/"
        )

        if offset == 0:
            return f"{base_url}{listing_path}"

        return (
            f"{base_url}{listing_path}"
            f"{offset}/"
        )

    def _extract_job_urls(
        self,
        page_html: str,
        base_url: str,
    ) -> list[str]:
        hrefs = re.findall(
            r'href=["\']([^"\']+)["\']',
            page_html,
            flags=re.IGNORECASE,
        )

        jobs: list[str] = []
        seen: set[str] = set()

        for href in hrefs:
            href = html.unescape(href)

            if "/job/" not in href:
                continue

            url = urljoin(
                base_url,
                href,
            )

            if url in seen:
                continue

            seen.add(url)
            jobs.append(url)

        return jobs

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

    def _extract_text(
        self,
        page_html: str,
    ) -> str:
        text = re.sub(
            r"<script\b[^>]*>.*?</script>",
            " ",
            page_html,
            flags=(
                re.IGNORECASE
                | re.DOTALL
            ),
        )

        text = re.sub(
            r"<style\b[^>]*>.*?</style>",
            " ",
            text,
            flags=(
                re.IGNORECASE
                | re.DOTALL
            ),
        )

        text = re.sub(
            r"<[^>]+>",
            " ",
            text,
        )

        text = html.unescape(text)

        return re.sub(
            r"\s+",
            " ",
            text,
        ).strip()

    def _extract_title(
        self,
        page_html: str,
    ) -> str | None:
        patterns = (
            r'<meta[^>]+property=["\']og:title["\']'
            r'[^>]+content=["\']([^"\']+)["\']',

            r'<meta[^>]+content=["\']([^"\']+)["\']'
            r'[^>]+property=["\']og:title["\']',

            r"<title>(.*?)</title>",
        )

        for pattern in patterns:
            match = re.search(
                pattern,
                page_html,
                flags=(
                    re.IGNORECASE
                    | re.DOTALL
                ),
            )

            if not match:
                continue

            title = html.unescape(
                re.sub(
                    r"<[^>]+>",
                    "",
                    match.group(1),
                )
            ).strip()

            # SAP title commonly looks like:
            #
            # Software Engineer Job Details |
            # Nomura Holdings, inc.
            title = re.sub(
                r"\s+Job Details\s*\|.*$",
                "",
                title,
                flags=re.IGNORECASE,
            ).strip()

            if title:
                return title

        return None

    def _extract_location(
        self,
        page_html: str,
    ) -> str:
        text = self._extract_text(
            page_html
        )

        patterns = (
            r"Location\s*:?\s*"
            r"(.{1,120}?)"
            r"(?=\s+(?:Job Code|"
            r"Requisition|Division|"
            r"Department|Job Type|"
            r"Date|Apply|$))",

            r"Primary Location\s*:?\s*"
            r"(.{1,120}?)"
            r"(?=\s+(?:Job Code|"
            r"Requisition|Division|"
            r"Department|Job Type|"
            r"Date|Apply|$))",
        )

        for pattern in patterns:
            match = re.search(
                pattern,
                text,
                flags=re.IGNORECASE,
            )

            if match:
                return (
                    match.group(1)
                    .strip(" :-|")
                )

        return "Unknown"

    def _extract_job_code(
        self,
        page_html: str,
        url: str,
    ) -> str:
        text = self._extract_text(
            page_html
        )

        patterns = (
            r"Job Code\s*:?\s*"
            r"([A-Za-z0-9_-]+)",

            r"Requisition\s+(?:ID|No\.?)"
            r"\s*:?\s*"
            r"([A-Za-z0-9_-]+)",
        )

        for pattern in patterns:
            match = re.search(
                pattern,
                text,
                flags=re.IGNORECASE,
            )

            if match:
                return match.group(1)

        # Stable fallback: SAP internal numeric ID in the URL.
        match = re.search(
            r"/(\d+)/?$",
            url,
        )

        if match:
            return match.group(1)

        return url

    def _extract_department(
        self,
        page_html: str,
    ) -> str | None:
        text = self._extract_text(
            page_html
        )

        for label in (
            "Division",
            "Department",
            "Skill Category",
        ):
            match = re.search(
                rf"{re.escape(label)}\s*:?\s*"
                r"(.{1,100}?)"
                r"(?=\s+(?:Division|"
                r"Department|Skill Category|"
                r"Job Code|Requisition|"
                r"Location|Apply|$))",
                text,
                flags=re.IGNORECASE,
            )

            if match:
                return (
                    match.group(1)
                    .strip(" :-|")
                )

        return None

    def _fetch_raw(
        self,
        company: Company,
    ) -> list[str]:
        """
        Fetch all unique job-detail URLs from the configured
        SuccessFactors RMK listing pages.

        SuccessFactors RMK exposes server-rendered HTML rather than
        the JSON payload used by most other provider adapters.
        """
        config = company.provider.config

        if not config.base_url:
            raise ValueError(
                f"{company.name}: SuccessFactors provider "
                "requires base_url"
            )

        page_size = (
            config.page_size
            or 100
        )

        job_urls: list[str] = []
        seen_urls: set[str] = set()

        for page_number in range(_MAX_PAGES):
            offset = page_number * page_size

            listing_url = self._listing_url(
                company,
                offset,
            )

            page_html = self._fetch_html(
                listing_url,
                company,
            )

            urls = self._extract_job_urls(
                page_html,
                config.base_url,
            )

            if not urls:
                break

            new_urls = [
                url
                for url in urls
                if url not in seen_urls
            ]

            if not new_urls:
                break

            for url in new_urls:
                seen_urls.add(url)
                job_urls.append(url)

            if len(urls) < page_size:
                break

        else:
            raise RuntimeError(
                f"{company.name}: SuccessFactors "
                f"pagination exceeded "
                f"{_MAX_PAGES} pages"
            )

        return job_urls

    def fetch_jobs(
        self,
        company: Company,
    ) -> list[Job]:
        job_urls = self._fetch_raw(
            company
        )

        jobs: list[Job] = []

        for url in job_urls:
            try:
                page_html = self._fetch_html(
                    url,
                    company,
                )

                title = self._extract_title(
                    page_html
                )

                if not title:
                    continue

                jobs.append(
                    Job(
                        id=self._extract_job_code(
                            page_html,
                            url,
                        ),
                        title=title,
                        company=company.name,
                        location=self._extract_location(
                            page_html
                        ),
                        url=url,
                        department=(
                            self._extract_department(
                                page_html
                            )
                        ),
                    )
                )

            except requests.RequestException:
                continue

        return jobs

    def parse(
        self,
        raw,
        company: Company,
    ) -> list[Job]:
        # SuccessFactors RMK is HTML based and therefore
        # fetch_jobs performs the parsing directly.
        return raw

    def validate(
        self,
        company: Company,
    ) -> bool:
        try:
            url = self._listing_url(
                company,
                0,
            )

            page_html = self._fetch_html(
                url,
                company,
            )

            urls = self._extract_job_urls(
                page_html,
                company.provider.config.base_url
                or url,
            )

            return bool(urls)

        except (
            requests.RequestException,
            ValueError,
        ):
            return False