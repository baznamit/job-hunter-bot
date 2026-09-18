from __future__ import annotations

from datetime import datetime

import requests

from models import Job
from models.company import Company

from .base import ProviderAdapter


class ZohoRecruitAdapter(
    ProviderAdapter
):
    provider_name = "Zoho Recruit"

    def _fetch_raw(
        self,
        company: Company,
    ) -> dict:
        config = company.provider.config

        if not config.api_url:
            raise ValueError(
                f"{company.name}: "
                "missing Zoho Recruit api_url"
            )

        response = requests.get(
            config.api_url,
            params={
                "pagename": (
                    config.page_name
                    or "Careers"
                ),
                "source": (
                    config.source
                    or "CareerSite"
                ),
            },
            headers={
                "Accept": "application/json",
                "User-Agent": (
                    "Mozilla/5.0 "
                    "(compatible; "
                    "JobHunterBot/1.0)"
                ),
            },
            timeout=30,
        )

        self._check_response(
            response,
            company,
        )

        payload = response.json()

        if not isinstance(
            payload,
            dict,
        ):
            raise ValueError(
                f"{company.name}: "
                "unexpected Zoho Recruit "
                "response"
            )

        return payload

    def parse(
        self,
        raw: dict | list,
        company: Company,
    ) -> list[Job]:
        if not isinstance(raw, dict):
            raise ValueError(
                f"{company.name}: "
                "expected Zoho Recruit "
                "object response"
            )

        items = raw.get("data")

        if not isinstance(
            items,
            list,
        ):
            raise ValueError(
                f"{company.name}: "
                "Zoho Recruit response "
                "missing data list"
            )

        jobs: list[Job] = []

        for item in items:
            if not isinstance(
                item,
                dict,
            ):
                continue

            job_id = str(
                item.get("id")
                or ""
            ).strip()

            title = str(
                item.get("Posting_Title")
                or item.get(
                    "Job_Opening_Name"
                )
                or ""
            ).strip()

            city = str(
                item.get("City")
                or ""
            ).strip()

            country = str(
                item.get("Country")
                or ""
            ).strip()

            url = str(
                item.get("$url")
                or ""
            ).strip()

            if not (
                job_id
                and title
                and url
            ):
                continue

            location = city

            if country:
                location = (
                    f"{city}, {country}"
                    if city
                    else country
                )

            posted_at = None

            raw_date = str(
                item.get("Date_Opened")
                or ""
            ).strip()

            if raw_date:
                try:
                    posted_at = (
                        datetime.strptime(
                            raw_date,
                            "%m/%d/%Y",
                        )
                    )
                except ValueError:
                    pass

            jobs.append(
                Job(
                    id=job_id,
                    title=title,
                    company=company.name,
                    location=location,
                    url=url,
                    posted_at=posted_at,
                    employment_type=(
                        str(
                            item.get(
                                "Job_Type"
                            )
                            or ""
                        ).strip()
                        or None
                    ),
                )
            )

        return jobs
