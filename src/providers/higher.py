import uuid

import requests

from models import Job
from models.company import Company

from .base import ProviderAdapter


_TIMEOUT = 30
_PAGE_SIZE = 20
_MAX_PAGES = 200


_QUERY = """
query GetRoles($searchQueryInput: RoleSearchQueryInput!) {
  roleSearch(searchQueryInput: $searchQueryInput) {
    totalCount
    items {
      roleId
      corporateTitle
      jobTitle
      jobFunction
      locations {
        primary
        state
        country
        city
      }
      status
      division
      skills
      jobType {
        code
        description
      }
      externalSource {
        sourceId
      }
    }
  }
}
"""


class HigherAdapter(ProviderAdapter):

    provider_name = "Higher"

    def _headers(
        self,
        session_id: str,
    ) -> dict[str, str]:
        return {
            "User-Agent": (
                "Mozilla/5.0 "
                "(compatible; JobHunterBot/1.0)"
            ),
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": "https://higher.gs.com",
            "Referer": "https://higher.gs.com/results",
            "x-higher-request-id": str(uuid.uuid4()),
            "x-higher-session-id": session_id,
        }

    def _payload(
        self,
        page_number: int,
    ) -> dict:
        return {
            "operationName": "GetRoles",
            "variables": {
                "searchQueryInput": {
                    "page": {
                        "pageSize": _PAGE_SIZE,
                        "pageNumber": page_number,
                    },
                    "filters": [],
                    "experiences": [
                        "EARLY_CAREER",
                        "PROFESSIONAL",
                    ],
                    "searchTerm": "",
                }
            },
            "query": _QUERY,
        }

    def _fetch_raw(
        self,
        company: Company,
    ) -> dict:
        config = company.provider.config

        if not config.graphql_url:
            raise ValueError(
                f"{company.name}: Higher provider "
                "requires graphql_url"
            )

        session_id = str(uuid.uuid4())

        all_jobs: list[dict] = []
        seen_ids: set[str] = set()

        total: int | None = None

        for page_number in range(_MAX_PAGES):
            response = requests.post(
                config.graphql_url,
                json=self._payload(page_number),
                headers=self._headers(session_id),
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
                    f"{company.name}: Higher API returned "
                    "a non-JSON response "
                    f"(status={response.status_code}, "
                    f"url={response.url})"
                ) from exc

            errors = data.get("errors")

            if errors:
                raise RuntimeError(
                    f"{company.name}: Higher GraphQL "
                    f"returned errors: {errors}"
                )

            role_search = (
                data.get("data", {})
                .get("roleSearch")
            )

            if not isinstance(role_search, dict):
                raise RuntimeError(
                    f"{company.name}: Higher API returned "
                    "an unexpected response shape"
                )

            reported_total = role_search.get(
                "totalCount"
            )

            if (
                isinstance(reported_total, int)
                and reported_total >= 0
            ):
                total = reported_total

            items = role_search.get("items") or []

            if not items:
                break

            new_count = 0

            for item in items:
                role_id = item.get("roleId")

                if not role_id:
                    continue

                role_id = str(role_id)

                if role_id in seen_ids:
                    continue

                seen_ids.add(role_id)
                all_jobs.append(item)
                new_count += 1

            if new_count == 0:
                raise RuntimeError(
                    f"{company.name}: Higher pagination "
                    f"stalled at page {page_number}"
                )

            consumed = (
                (page_number + 1)
                * _PAGE_SIZE
            )

            if (
                total is not None
                and consumed >= total
            ):
                break

            if len(items) < _PAGE_SIZE:
                break

        else:
            raise RuntimeError(
                f"{company.name}: Higher pagination "
                f"exceeded {_MAX_PAGES} pages"
            )

        return {
            "items": all_jobs,
            "total": total,
        }

    def _location(
        self,
        item: dict,
    ) -> str:
        locations = item.get("locations") or []

        if not locations:
            return "Unknown"

        primary = next(
            (
                location
                for location in locations
                if location.get("primary")
            ),
            locations[0],
        )

        parts = [
            primary.get("city"),
            primary.get("state"),
            primary.get("country"),
        ]

        return ", ".join(
            str(part)
            for part in parts
            if part
        ) or "Unknown"

    def parse(
        self,
        raw: dict,
        company: Company,
    ) -> list[Job]:
        jobs: list[Job] = []

        base_url = (
            company.provider.config.public_base_url
            or "https://higher.gs.com"
        ).rstrip("/")

        for item in raw.get("items", []):
            try:
                role_id = str(item["roleId"])
                title = item["jobTitle"]

                external_source = (
                    item.get("externalSource")
                    or {}
                )

                source_id = external_source.get(
                    "sourceId"
                )

                if not source_id:
                    continue

                department = (
                    item.get("division")
                    or item.get("jobFunction")
                )

                jobs.append(
                    Job(
                        id=role_id,
                        title=title,
                        company=company.name,
                        location=self._location(item),
                        url=(
                            f"{base_url}/roles/"
                            f"{source_id}"
                        ),
                        department=department,
                    )
                )

            except (
                KeyError,
                TypeError,
                ValueError,
            ):
                continue

        return jobs

    def validate(
        self,
        company: Company,
    ) -> bool:
        config = company.provider.config

        if not config.graphql_url:
            return False

        session_id = str(uuid.uuid4())

        payload = self._payload(0)

        # Validation only needs one result.
        payload["variables"]["searchQueryInput"]["page"] = {
            "pageSize": 1,
            "pageNumber": 0,
        }

        response = requests.post(
            config.graphql_url,
            json=payload,
            headers=self._headers(session_id),
            timeout=_TIMEOUT,
        )

        self._check_response(
            response,
            company,
        )

        try:
            data = response.json()
        except requests.exceptions.JSONDecodeError:
            return False

        if data.get("errors"):
            return False

        role_search = (
            data.get("data", {})
            .get("roleSearch")
        )

        return (
            isinstance(role_search, dict)
            and "totalCount" in role_search
            and "items" in role_search
        )