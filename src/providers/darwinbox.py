from datetime import datetime

import requests

from models import Job
from models.company import Company

from .base import ProviderAdapter

_TIMEOUT = 20
_DEFAULT_API_URL = "https://service.upstox.com/content/open/v1/jobs/"
_DEFAULT_JOB_URL = (
    "https://upstox.darwinbox.in/ms/candidatev2/main/"
    "careers/jobDetails/{job_id}?from=all"
)


class DarwinboxAdapter(ProviderAdapter):
    """Adapter for Darwinbox public job feeds, verified with Upstox."""

    provider_name = "Darwinbox"

    def _fetch_raw(self, company: Company) -> dict:
        response = requests.get(
            company.provider.config.api_url or _DEFAULT_API_URL,
            headers={
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0 (compatible; JobHunterBot/1.0)",
            },
            timeout=_TIMEOUT,
        )
        self._check_response(response, company)

        try:
            raw = response.json()
        except requests.exceptions.JSONDecodeError as exc:
            raise RuntimeError(
                f"{company.name}: Darwinbox returned non-JSON response"
            ) from exc

        if not isinstance(raw, dict) or not isinstance(raw.get("data"), list):
            raise RuntimeError(
                f"{company.name}: Darwinbox returned an unexpected response shape"
            )
        return raw

    @staticmethod
    def _location(item: dict) -> str:
        cities = item.get("location_city")
        if isinstance(cities, list):
            city_names = [str(city).strip() for city in cities if city]
            if city_names:
                return ", ".join(dict.fromkeys(city_names))

        locations = item.get("location")
        if isinstance(locations, list):
            names = [str(location).strip() for location in locations if location]
            if names:
                return ", ".join(dict.fromkeys(names))
        if isinstance(locations, str) and locations.strip():
            return locations.strip()
        return "Unknown"

    @staticmethod
    def _posted_at(value: object) -> datetime | None:
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            return datetime.strptime(value, "%d-%m-%Y %H:%M:%S")
        except ValueError:
            return None

    @staticmethod
    def _is_remote(value: object) -> bool:
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes"}
        return value is True or value == 1

    def parse(self, raw: dict, company: Company) -> list[Job]:
        records = raw.get("data")
        if not isinstance(records, list):
            return []

        jobs: list[Job] = []
        for item in records:
            if not isinstance(item, dict) or item.get("post_on_careers_page") != 1:
                continue

            job_id = item.get("job_id")
            title = item.get("job_title")
            if not job_id or not title:
                continue

            try:
                jobs.append(
                    Job(
                        id=str(job_id),
                        title=str(title).strip(),
                        company=company.name,
                        location=self._location(item),
                        url=_DEFAULT_JOB_URL.format(job_id=job_id),
                        posted_at=self._posted_at(
                            item.get("job_created_timestamp")
                        ),
                        department=item.get("department") or None,
                        employment_type=item.get("employee_type") or None,
                        remote=self._is_remote(item.get("is_remote")),
                    )
                )
            except (TypeError, ValueError):
                continue
        return jobs

    def validate(self, company: Company) -> bool:
        raw = self._fetch_raw(company)
        return any(
            isinstance(item, dict)
            and item.get("post_on_careers_page") == 1
            and item.get("job_id")
            and item.get("job_title")
            for item in raw["data"]
        )
