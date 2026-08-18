import requests

from models import Job
from models.company import Company

from .base import ProviderAdapter


_TIMEOUT = 20
_PAGE_SIZE = 100


class SmartRecruitersAdapter(ProviderAdapter):

    provider_name = "SmartRecruiters"

    def _fetch_raw(self, company: Company) -> dict:
        identifier = company.provider.config.company_identifier

        url = (
            "https://api.smartrecruiters.com/v1/companies/"
            f"{identifier}/postings"
        )

        all_content: list[dict] = []
        offset = 0

        while True:
            response = requests.get(
                url,
                params={
                    "limit": _PAGE_SIZE,
                    "offset": offset,
                },
                headers={
                    "Accept": "application/json",
                },
                timeout=_TIMEOUT,
            )

            self._check_response(response, company)

            data = response.json()
            content = data.get("content", [])

            all_content.extend(content)

            if not content:
                break

            total = data.get("totalFound")

            offset += len(content)

            if total is not None and offset >= total:
                break

            if len(content) < _PAGE_SIZE:
                break

        return {"content": all_content}

    def parse(
        self,
        raw: dict,
        company: Company,
    ) -> list[Job]:
        jobs: list[Job] = []

        identifier = company.provider.config.company_identifier

        for item in raw.get("content", []):
            try:
                posting_id = str(item["id"])
                title = item["name"]

                location_data = item.get("location") or {}

                location_parts = [
                    location_data.get("city"),
                    location_data.get("region"),
                    location_data.get("country"),
                ]

                location = ", ".join(
                    part
                    for part in location_parts
                    if part
                ) or "Unknown"

                department_data = (
                    item.get("department")
                    or {}
                )

                department = (
                    department_data.get("label")
                    or department_data.get("name")
                )

                url = (
                    "https://jobs.smartrecruiters.com/"
                    f"{identifier}/{posting_id}"
                )

                jobs.append(
                    Job(
                        id=posting_id,
                        title=title,
                        company=company.name,
                        location=location,
                        url=url,
                        department=department,
                        posted_at=None,
                    )
                )

            except Exception:
                continue

        return jobs

    def validate(self, company: Company) -> bool:
        identifier = company.provider.config.company_identifier

        if not identifier:
            return False

        url = (
            "https://api.smartrecruiters.com/v1/companies/"
            f"{identifier}/postings"
        )

        response = requests.get(
            url,
            params={
                "limit": 1,
                "offset": 0,
            },
            headers={
                "Accept": "application/json",
            },
            timeout=_TIMEOUT,
        )

        self._check_response(response, company)

        data = response.json()

        return (
            isinstance(data, dict)
            and "content" in data
        )