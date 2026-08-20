import html
import math
import re
from urllib.parse import urljoin

import requests

from models import Job
from models.company import Company

from .base import ProviderAdapter


_TIMEOUT = 30
_MAX_PAGES = 500


class TalentBrewAdapter(ProviderAdapter):
    provider_name = "TalentBrew"

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

    def _fetch_html(
        self,
        url: str,
        company: Company,
        *,
        params: dict | None = None,
    ) -> str:
        response = requests.get(
            url,
            params=params,
            headers=self._headers(),
            timeout=_TIMEOUT,
            allow_redirects=True,
        )

        self._check_response(
            response,
            company,
        )

        return response.text

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

    def _extract_total(
        self,
        page_html: str,
    ) -> int | None:
        patterns = (
            r'<h2[^>]*class=["\'][^"\']*sr-heading[^"\']*["\'][^>]*>'
            r'\s*([\d,]+)\s+Results',

            r'<h1[^>]*class=["\'][^"\']*search-results-heading[^"\']*["\'][^>]*>'
            r'\s*([\d,]+)\s+jobs?\s+found',

            r'\b([\d,]+)\s+Results\b',

            r'\b([\d,]+)\s+jobs?\s+found\b',
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
        config = company.provider.config

        if not config.base_url:
            raise ValueError(
                f"{company.name}: TalentBrew provider "
                "requires base_url"
            )

        # TalentBrew search results are represented as <li>
        # elements. Metadata such as location may be outside
        # the job <a>, so parse the complete result item.
        items = re.findall(
            r'<li\b[^>]*class=["\'][^"\']*'
            r'(?:sr-job-item|search-results-li)'
            r'[^"\']*["\'][^>]*>'
            r'(.*?)</li>',
            page_html,
            flags=(
                re.IGNORECASE
                | re.DOTALL
            ),
        )

        jobs: list[Job] = []
        seen: set[str] = set()

        for item in items:
            anchor = re.search(
                r'<a\b([^>]*\bdata-job-id='
                r'["\'][^"\']+["\'][^>]*)>'
                r'(.*?)</a>',
                item,
                flags=(
                    re.IGNORECASE
                    | re.DOTALL
                ),
            )

            if not anchor:
                continue

            attrs = anchor.group(1)
            body = anchor.group(2)

            id_match = re.search(
                r'data-job-id=["\']([^"\']+)["\']',
                attrs,
                flags=re.IGNORECASE,
            )

            href_match = re.search(
                r'href=["\']([^"\']+)["\']',
                attrs,
                flags=re.IGNORECASE,
            )

            if not id_match or not href_match:
                continue

            job_id = html.unescape(
                id_match.group(1)
            )

            href = html.unescape(
                href_match.group(1)
            )

            if "/job/" not in href.lower():
                continue

            if job_id in seen:
                continue

            seen.add(job_id)

            url = urljoin(
                config.base_url,
                href,
            )

            title = self._extract_title(
                body
            )

            # Location/department can live outside the anchor,
            # so inspect the complete result item.
            location = self._extract_location(
                item
            )

            department = self._extract_department(
                item
            )

            if not title:
                continue

            jobs.append(
                Job(
                    id=job_id,
                    title=title,
                    company=company.name,
                    location=location,
                    url=url,
                    department=department,
                )
            )

        return jobs

    def _extract_title(
        self,
        body: str,
    ) -> str:
        # BlackRock puts the title in a heading inside the anchor.
        heading = re.search(
            r'<h[1-6][^>]*>(.*?)</h[1-6]>',
            body,
            flags=(
                re.IGNORECASE
                | re.DOTALL
            ),
        )

        if heading:
            return self._clean_text(
                heading.group(1)
            )

        # Citi puts the title directly inside the anchor.
        # Remove known metadata elements first.
        cleaned = re.sub(
            r'<span\b[^>]*class=["\'][^"\']*'
            r'(?:job-location|job-category|job-information)'
            r'[^"\']*["\'][^>]*>.*?</span>',
            " ",
            body,
            flags=(
                re.IGNORECASE
                | re.DOTALL
            ),
        )

        return self._clean_text(
            cleaned
        )

    def _extract_location(
        self,
        body: str,
    ) -> str:
        patterns = (
            # Citi
            r'<span[^>]*class=["\'][^"\']*'
            r'sr-job-location[^"\']*["\'][^>]*>'
            r'(.*?)</span>',

            # BlackRock: Location: <span class="...job-info">...</span>
            r'Location:\s*</span>\s*'
            r'<span[^>]*class=["\'][^"\']*'
            r'job-info[^"\']*["\'][^>]*>'
            r'(.*?)</span>',
        )

        for pattern in patterns:
            match = re.search(
                pattern,
                body,
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
        body: str,
    ) -> str | None:
        match = re.search(
            r'(?:Team|Category):\s*</span>\s*'
            r'<span[^>]*class=["\'][^"\']*'
            r'job-info[^"\']*["\'][^>]*>'
            r'(.*?)</span>',
            body,
            flags=(
                re.IGNORECASE
                | re.DOTALL
            ),
        )

        if not match:
            return None

        value = self._clean_text(
            match.group(1)
        )

        return value or None

    def _fetch_raw(
        self,
        company: Company,
    ) -> list[Job]:
        config = company.provider.config

        if not config.base_url:
            raise ValueError(
                f"{company.name}: TalentBrew provider "
                "requires base_url"
            )

        page_size = config.page_size

        if not page_size:
            raise ValueError(
                f"{company.name}: TalentBrew provider "
                "requires page_size"
            )

        search_url = (
            config.base_url.rstrip("/")
            + "/search-jobs"
        )

        jobs: list[Job] = []
        seen_ids: set[str] = set()

        total: int | None = None

        for page in range(
            1,
            _MAX_PAGES + 1,
        ):
            page_html = self._fetch_html(
                search_url,
                company,
                params={"p": page},
            )

            if total is None:
                total = self._extract_total(
                    page_html
                )

            page_jobs = self._extract_jobs(
                page_html,
                company,
            )

            if not page_jobs:
                break
            else:
                new_jobs = [
                    job
                    for job in page_jobs
                    if job.id not in seen_ids
                ]

                if not new_jobs:
                    break

                for job in new_jobs:
                    seen_ids.add(job.id)
                    jobs.append(job)

                if total is not None:
                    expected_pages = math.ceil(
                        total / page_size
                    )

                    if page >= expected_pages:
                        break

                elif len(page_jobs) < page_size:
                    break

        else:
            raise RuntimeError(
                f"{company.name}: TalentBrew "
                f"pagination exceeded "
                f"{_MAX_PAGES} pages"
            )

        return jobs

    def parse(
        self,
        raw,
        company: Company,
    ) -> list[Job]:
        # _fetch_raw already converts the server-rendered
        # TalentBrew search result HTML into normalized jobs.
        return raw

    def validate(
        self,
        company: Company,
    ) -> bool:
        config = company.provider.config

        if not config.base_url:
            return False

        try:
            page_html = self._fetch_html(
                (
                    config.base_url.rstrip("/")
                    + "/search-jobs"
                ),
                company,
                params={"p": 1},
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