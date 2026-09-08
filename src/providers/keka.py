from datetime import datetime

import requests

from models import Job
from models.company import Company

from .base import ProviderAdapter

_TIMEOUT = 20

class KekaAdapter(ProviderAdapter):

    provider_name = "Keka"

    def _api_url(
        self,
        company: Company,
    ) -> str:
        config = company.provider.config

        if not config.base_url:
            raise ValueError(
                f"{company.name}: Keka provider "
                "requires base_url"
            )

        if not config.identifier:
            raise ValueError(
                f"{company.name}: Keka provider "
                "requires identifier"
            )

        portal_name = (
            config.portal_name
            or "default"
        )

        return (
            f"{config.base_url.rstrip('/')}/"
            f"api/embedjobs/"
            f"{portal_name}/active/"
            f"{config.identifier}"
        )

    def _fetch_raw(
        self,
        company: Company,
    ) -> dict | list:
        response = requests.get(
            self._api_url(company),
            headers={
                "Accept": "application/json",
                "User-Agent": (
                    "Mozilla/5.0 "
                    "(compatible; JobHunterBot/1.0)"
                ),
            },
            timeout=_TIMEOUT,
        )

        self._check_response(
            response,
            company,
        )

        try:
            data = response.json()
        except requests.exceptions.JSONDecodeError as exc:
            raise RuntimeError(
                f"{company.name}: Keka API "
                "returned non-JSON response"
            ) from exc

        if not isinstance(
            data,
            (dict, list),
        ):
            raise RuntimeError(
                f"{company.name}: Keka API "
                "returned unexpected response shape"
            )

        return data

    @staticmethod
    def _items(
        raw: dict | list,
    ) -> list[dict]:
        if isinstance(raw, list):
            return raw

        for key in (
            "jobs",
            "data",
            "results",
        ):
            value = raw.get(key)

            if isinstance(value, list):
                return value

        return []

    @staticmethod
    def _location(
        item: dict,
    ) -> str:
        locations = (
            item.get("jobLocations")
            or []
        )

        if not isinstance(
            locations,
            list,
        ):
            return "Unknown"

        formatted: list[str] = []

        for location in locations:
            if not isinstance(
                location,
                dict,
            ):
                continue

            parts = [
                location.get("city")
                or location.get("name"),
                location.get("stateName")
                or location.get("state"),
                location.get("countryName")
                or location.get("country"),
            ]

            text = ", ".join(
                str(part).strip()
                for part in parts
                if part
            )

            if (
                text
                and text not in formatted
            ):
                formatted.append(text)

        return (
            " / ".join(formatted)
            or "Unknown"
        )

    @staticmethod
    def _job_id(
        item: dict,
    ) -> str | None:
        for key in (
            "identifier",
            "jobIdentifier",
            "id",
            "jobNumber",
        ):
            value = item.get(key)

            if value is not None:
                return str(value)

        return None

    @staticmethod
    def _employment_type(
        item: dict,
    ) -> str | None:
        value = item.get(
            "jobType"
        )

        if value is None:
            return None

        # Keka currently returns a numeric enum.
        # Keep the normalized model type-safe even if
        # Keka changes/adds enum values.
        return str(value)

    @staticmethod
    def _posted_at(
        item: dict,
    ) -> datetime | None:
        value = item.get(
            "publishedOn"
        )

        if not value:
            return None

        try:
            return datetime.fromisoformat(
                str(value).replace(
                    "Z",
                    "+00:00",
                )
            )
        except ValueError:
            return None

    def _job_url(
        self,
        item: dict,
        company: Company,
        job_id: str,
    ) -> str:
        for key in (
            "jobUrl",
            "applyUrl",
            "url",
        ):
            value = item.get(key)

            if value:
                return str(value)

        config = company.provider.config

        return (
            f"{config.base_url.rstrip('/')}/"
            f"jobdetails/{job_id}"
        )

    def parse(
        self,
        raw: dict | list,
        company: Company,
    ) -> list[Job]:
        jobs: list[Job] = []

        for item in self._items(raw):
            if not isinstance(
                item,
                dict,
            ):
                continue

            job_id = self._job_id(
                item
            )

            title = item.get(
                "title"
            )

            if not job_id or not title:
                continue

            jobs.append(
                Job(
                    id=job_id,
                    title=str(
                        title
                    ).strip(),
                    company=company.name,
                    location=self._location(
                        item
                    ),
                    url=self._job_url(
                        item,
                        company,
                        job_id,
                    ),
                    posted_at=self._posted_at(
                        item
                    ),
                    department=(
                        item.get(
                            "departmentName"
                        )
                        or item.get(
                            "department"
                        )
                        or None
                    ),
                    employment_type=(
                        self._employment_type(
                            item
                        )
                    ),
                )
            )

        return jobs

    def validate(
        self,
        company: Company,
    ) -> bool:
        raw = self._fetch_raw(
            company
        )

        return isinstance(
            raw,
            (dict, list),
        )
