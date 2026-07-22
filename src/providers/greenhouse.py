from datetime import datetime

import requests

from models import Job
from models.company import Company

from .base import ProviderAdapter

_BASE_URL = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs"
_TIMEOUT = 20


class GreenhouseAdapter(ProviderAdapter):

    def _fetch_raw(self, company: Company) -> dict:
        board = company.provider.config.board
        url = _BASE_URL.format(board=board)
        response = requests.get(url, timeout=_TIMEOUT)
        response.raise_for_status()
        return response.json()

    def parse(self, raw: dict, company: Company) -> list[Job]:
        jobs = []
        for item in raw.get("jobs", []):
            job = self._parse_item(item, company)
            if job is not None:
                jobs.append(job)
        return jobs

    def _parse_item(self, item: dict, company: Company) -> Job | None:
        try:
            location = "Unknown"
            if item.get("location"):
                location = item["location"].get("name") or "Unknown"

            posted_at = None
            if item.get("updated_at"):
                posted_at = datetime.fromisoformat(
                    item["updated_at"].replace("Z", "+00:00")
                )

            department = None
            departments = item.get("departments") or []
            if departments:
                department = departments[0].get("name")

            return Job(
                id=str(item["id"]),
                title=item["title"],
                company=company.name,
                location=location,
                url=item["absolute_url"],
                posted_at=posted_at,
                department=department,
            )
        except Exception:
            return None