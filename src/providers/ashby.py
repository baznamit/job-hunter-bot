from datetime import datetime, timezone

import requests

from models import Job
from models.company import Company

from .base import ProviderAdapter

_BASE_URL = "https://api.ashbyhq.com/posting-api/job-board/{org}"
_TIMEOUT = 20


class AshbyAdapter(ProviderAdapter):

    def _fetch_raw(self, company: Company) -> dict:
        org = company.provider.config.organization
        url = _BASE_URL.format(org=org)
        response = requests.get(url, timeout=_TIMEOUT)
        response.raise_for_status()
        return response.json()

    def parse(self, raw: dict, company: Company) -> list[Job]:
        jobs = []
        for item in raw.get("jobPostings", []):
            job = self._parse_item(item, company)
            if job is not None:
                jobs.append(job)
        return jobs

    def _parse_item(self, item: dict, company: Company) -> Job | None:
        try:
            location = item.get("locationName") or "Unknown"

            posted_at = None
            if item.get("publishedDate"):
                posted_at = datetime.fromisoformat(item["publishedDate"]).replace(
                    tzinfo=timezone.utc
                )

            return Job(
                id=item["id"],
                title=item["title"],
                company=company.name,
                location=location,
                url=item["jobUrl"],
                posted_at=posted_at,
                department=item.get("departmentName"),
                remote=item.get("isRemote", False),
            )
        except Exception:
            return None