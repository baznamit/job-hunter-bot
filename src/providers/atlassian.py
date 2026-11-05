"""Atlassian official careers HTML adapter."""

import re
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from models import Job
from models.company import Company

from .base import ProviderAdapter

_LISTING = "https://www.atlassian.com/company/careers/all-jobs"
_BASE = "https://www.atlassian.com"
_TIMEOUT = (8, 20)

_JOB_PATH = re.compile(
    r"^/company/careers/details/(\d+)/?$"
)


class AtlassianAdapter(ProviderAdapter):
    provider_name = "Atlassian"

    def _get_html(self, url: str, company: Company) -> str:
        response = requests.get(
            url,
            timeout=_TIMEOUT,
            headers={
                "Accept": "text/html",
                "User-Agent": "JobHunterBot/1.0",
            },
        )
        self._check_response(response, company)

        if "html" not in response.headers.get(
            "Content-Type", ""
        ).lower():
            raise ValueError(
                f"{company.name}: expected HTML from {url}"
            )

        return response.text

    @staticmethod
    def _listing_items(html: str) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        items = {}
        for anchor in soup.select("a[href]"):
            absolute = urljoin(_BASE, anchor["href"])
            parsed = urlparse(absolute)

            if parsed.hostname != "www.atlassian.com":
                continue

            match = _JOB_PATH.fullmatch(parsed.path)
            if not match:
                continue

            title = anchor.get_text(" ", strip=True)
            if not title:
                continue

            job_id = match.group(1)
            items[job_id] = {
                "id": job_id,
                "title": title,
                "url": f"{_BASE}/company/careers/details/{job_id}",
            }

        return list(items.values())

    @staticmethod
    def _detail_metadata(html: str, expected_title: str) -> dict:
        soup = BeautifulSoup(html, "html.parser")
        main = soup.select_one("main#content")
        if main is None:
            raise ValueError("Atlassian detail missing main#content")

        heading = main.find("h1")
        if heading is None:
            raise ValueError("Atlassian detail missing h1")

        title = heading.get_text(" ", strip=True)
        if not title:
            raise ValueError("Atlassian detail has empty title")

        # Find the smallest heading ancestor containing the
        # job's application action, avoiding global navigation.
        header = None
        for parent in heading.parents:
            if parent is main:
                break
            if parent.find(
                "a",
                string=re.compile(
                    r"Apply for this job", re.I
                ),
            ):
                header = parent
                break

        if header is None:
            raise ValueError(
                "Atlassian job-specific header not found"
            )

        header_text = header.get_text(" ", strip=True)
        location = ""

        # Observed format:
        # Title Engineering | Bengaluru, India |
        # Remote, Remote Apply for this job
        parts = [
            part.strip()
            for part in header_text.split("|")
        ]

        if len(parts) >= 2:
            location_parts = parts[1:]
            location = " | ".join(location_parts)
            location = re.sub(
                r"\s*Apply for this job.*$",
                "",
                location,
                flags=re.I,
            ).strip()

        if not location:
            raise ValueError(
                "Atlassian location could not be extracted"
            )

        apply_url = None
        for anchor in header.select("a[href]"):
            if re.search(
                r"Apply for this job",
                anchor.get_text(" ", strip=True),
                re.I,
            ):
                candidate = urljoin(
                    _BASE, anchor["href"]
                )
                if urlparse(candidate).hostname and (
                    urlparse(candidate).hostname.endswith(
                        ".icims.com"
                    )
                ):
                    apply_url = candidate
                    break

        if not apply_url:
            raise ValueError(
                "Atlassian official Apply link not found"
            )

        return {
            "title": title,
            "location": location,
            "apply_url": apply_url,
            "description": main.get_text(" ", strip=True),
        }

    def _fetch_raw(self, company: Company) -> list[dict]:
        config = company.provider.config
        listing_url = config.base_url or _LISTING

        listing_html = self._get_html(
            listing_url, company
        )
        items = self._listing_items(listing_html)

        if not items:
            raise ValueError(
                f"{company.name}: zero listing job links"
            )

        limit = config.detail_limit
        if limit is not None:
            items = items[:limit]

        results = []
        for item in items:
            try:
                detail_html = self._get_html(
                    item["url"], company
                )
                metadata = self._detail_metadata(
                    detail_html, item["title"]
                )
                results.append({
                    **item,
                    **metadata,
                })
            except (requests.RequestException, ValueError) as exc:
                print(
                    f"[ATLASSIAN] DETAIL_FAILED "
                    f"id={item['id']} "
                    f"error={type(exc).__name__}: {exc}"
                )

        if not results:
            raise ValueError(
                f"{company.name}: no usable job details"
            )

        return results

    def parse(
        self,
        raw: list[dict],
        company: Company,
    ) -> list[Job]:
        jobs = []
        seen = set()

        for item in raw:
            job_id = str(item["id"])
            if job_id in seen:
                continue

            seen.add(job_id)

            location = item["location"]

            jobs.append(
                Job(
                    id=job_id,
                    title=item["title"],
                    company=company.name,
                    location=location,
                    url=item["url"],
                    department="Engineering",
                    remote=bool(
                        re.search(
                            r"\bremote\b",
                            location,
                            re.I,
                        )
                    ),
                )
            )

        return jobs
