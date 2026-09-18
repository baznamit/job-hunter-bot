from __future__ import annotations

from datetime import datetime

import requests

from models import Job
from models.company import Company

from .base import ProviderAdapter

_TIMEOUT = 30


class FyndAdapter(ProviderAdapter):
    provider_name = "Fynd Careers"

    def _fetch_raw(
        self,
        company: Company,
    ) -> dict:
        base_url = (
            company.provider.config.base_url
            or "https://hiring.fynd.com"
        ).rstrip("/")

        response = requests.get(
            (
                f"{base_url}/api/public/"
                "careers/gofynd/jobs"
            ),
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
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError(
                f"{company.name}: "
                "Fynd careers endpoint "
                "returned non-JSON"
            ) from exc

        if not isinstance(payload, dict):
            raise RuntimeError(
                f"{company.name}: "
                "unexpected Fynd response"
            )

        if payload.get("success") is not True:
            raise RuntimeError(
                f"{company.name}: "
                "Fynd careers API "
                "reported failure"
            )

        if not isinstance(
            payload.get("jobs"),
            list,
        ):
            raise RuntimeError(
                f"{company.name}: "
                "Fynd response missing jobs"
            )

        return payload

    def parse(
        self,
        raw: dict | list,
        company: Company,
    ) -> list[Job]:
        if not isinstance(raw, dict):
            return []

        jobs: list[Job] = []

        for item in raw.get(
            "jobs",
            [],
        ):
            if not isinstance(
                item,
                dict,
            ):
                continue

            job_id = str(
                item.get("id")
                or ""
            ).strip()

            public_token = str(
                item.get("publicToken")
                or ""
            ).strip()

            title = str(
                item.get("title")
                or ""
            ).strip()

            location = str(
                item.get("location")
                or ""
            ).strip()

            if not (
                job_id
                and title
                and public_token
            ):
                continue

            posted_at = self._parse_date(
                item.get("publishedAt")
            )

            jobs.append(
                Job(
                    id=job_id,
                    title=title,
                    company=company.name,
                    location=(
                        location
                        or "Unknown"
                    ),
                    url=(
                        "https://hiring.fynd.com/"
                        f"careers/gofynd/jobs/"
                        f"{public_token}"
                    ),
                    posted_at=posted_at,
                    department=(
                        item.get("department")
                        or item.get("team")
                    ),
                    employment_type=(
                        item.get(
                            "employmentType"
                        )
                    ),
                )
            )

        return jobs

    @staticmethod
    def _parse_date(
        value: object,
    ) -> datetime | None:
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

    def validate(
        self,
        company: Company,
    ) -> bool:
        raw = self._fetch_raw(
            company
        )

        return bool(
            raw.get("jobs")
        )
