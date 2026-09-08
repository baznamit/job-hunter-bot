import requests

from models import Job
from models.company import Company

from .base import ProviderAdapter

_TIMEOUT = 20

_DEFAULT_API_URL = (
    "https://www.phonepe.com/"
    "apollo/job-postings/latest.json"
)

class PhonePeAdapter(ProviderAdapter):

    provider_name = "PhonePe"

    def _api_url(
        self,
        company: Company,
    ) -> str:
        return (
            company.provider.config.api_url
            or _DEFAULT_API_URL
        )

    def _fetch_raw(
        self,
        company: Company,
    ) -> dict:
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
                f"{company.name}: PhonePe API "
                "returned non-JSON response"
            ) from exc

        if not isinstance(data, dict):
            raise RuntimeError(
                f"{company.name}: PhonePe API "
                "returned unexpected response shape"
            )

        return data

    @staticmethod
    def _location(item: dict) -> str:
        location = item.get("location")

        if isinstance(location, str):
            return location.strip() or "Unknown"

        if isinstance(location, dict):
            parts = [
                location.get("city"),
                location.get("state"),
                location.get("country"),
            ]

            return ", ".join(
                str(part).strip()
                for part in parts
                if part
            ) or "Unknown"

        return "Unknown"

    @staticmethod
    def _job_id(
        item: dict,
        apply_url: str,
    ) -> str:
        for key in (
            "id",
            "jobId",
            "jobID",
            "jobPostingId",
            "requisitionId",
        ):
            value = item.get(key)

            if value:
                return str(value)

        # applyUrl is required by PhonePe's own frontend,
        # so it is a stable fallback identifier.
        return apply_url

    def parse(
        self,
        raw: dict,
        company: Company,
    ) -> list[Job]:
        results = raw.get("results")

        if not isinstance(results, list):
            return []

        jobs: list[Job] = []

        for item in results:
            if not isinstance(item, dict):
                continue

            # Match PhonePe's own frontend behaviour.
            if item.get("status") != "PUBLIC":
                continue

            apply_url = item.get("applyUrl")
            title = item.get("title")

            if not apply_url or not title:
                continue

            try:
                jobs.append(
                    Job(
                        id=self._job_id(
                            item,
                            apply_url,
                        ),
                        title=str(title).strip(),
                        company=company.name,
                        location=self._location(item),
                        url=apply_url,
                        department=(
                            item.get("department")
                            or None
                        ),
                        employment_type=(
                            item.get("type")
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

        results = raw.get("results")

        return isinstance(results, list)
