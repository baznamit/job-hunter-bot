from datetime import datetime, timezone

import requests

from models import Job
from models.company import Company

from .base import ProviderAdapter

# Returns a JSON array of postings.
_BASE_URL = "https://api.lever.co/v0/postings/{slug}?mode=json"
_TIMEOUT = 20


class LeverAdapter(ProviderAdapter):

    def _fetch_raw(self, company: Company) -> list:
        slug = company.provider.config.board
        url = _BASE_URL.format(slug=slug)
        response = requests.get(url, timeout=_TIMEOUT)
        response.raise_for_status()
        return response.json()

    def parse(self, raw: list, company: Company) -> list[Job]:
        jobs = []
        for item in raw:
            job = self._parse_item(item, company)
            if job is not None:
                jobs.append(job)
        return jobs

    def _parse_item(self, item: dict, company: Company) -> Job | None:
        try:
            categories = item.get("categories") or {}

            location = categories.get("location") or "Unknown"
            if location == "Unknown" and item.get("workplaceType") == "remote":
                location = "Remote"

            posted_at = None
            if item.get("createdAt"):
                posted_at = datetime.fromtimestamp(
                    item["createdAt"] / 1000, tz=timezone.utc
                )

            department = categories.get("department")

            return Job(
                id=item["id"],
                title=item["text"],
                company=company.name,
                location=location,
                url=item["hostedUrl"],
                posted_at=posted_at,
                department=department,
                remote=item.get("workplaceType") == "remote",
            )
        except Exception:
            return None