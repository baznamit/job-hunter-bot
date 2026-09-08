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

        if not isinstance(locations, list):
            return "Unknown"

        formatted: list[str] = []

        for location in locations:
            if not isinstance(location, dict):
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

            if value:
                return str(value)

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

        portal_name = (
            config.portal_name
            or "default"
        )

        return (
            f"{config.base_url.rstrip('/')}/"
            f"{portal_name}/jobdetails/"
            f"{job_id}"
        )

    def parse(
        self,
        raw: dict | list,
        company: Company,
    ) -> list[Job]:
        jobs: list[Job] = []

        for item in self._items(raw):
            if not isinstance(item, dict):
                continue

            job_id = self._job_id(item)
            title = item.get("title")

            if not job_id or not title:
                continue

            try:
                jobs.append(
                    Job(
                        id=job_id,
                        title=str(title).strip(),
                        company=company.name,
                        location=self._location(item),
                        url=self._job_url(
                            item,
                            company,
                            job_id,
                        ),
                        department=(
                            item.get("department")
                            or item.get(
                                "departmentName"
                            )
                            or None
                        ),
                        employment_type=(
                            item.get("jobType")
                            or None
                        ),
                    )
                )
            except (
                TypeError,
                ValueError,
            ):
                continue

        return jobs

    def validate(
        self,
        company: Company,
    ) -> bool:
        raw = self._fetch_raw(company)

        return isinstance(
            raw,
            (dict, list),
        )
