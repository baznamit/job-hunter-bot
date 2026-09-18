from __future__ import annotations

from datetime import datetime
from email.utils import parsedate_to_datetime
import xml.etree.ElementTree as ET

import requests

from models import Job
from models.company import Company

from .base import ProviderAdapter

_TIMEOUT = 45


class CognizantAdapter(ProviderAdapter):
    provider_name = "Cognizant"

    def _fetch_raw(
        self,
        company: Company,
    ) -> list[dict]:
        config = company.provider.config

        if not config.base_url:
            raise ValueError(
                f"{company.name}: Cognizant provider "
                "requires base_url"
            )

        url = (
            config.base_url.rstrip("/")
            + "/jobs/xml/?rss=true"
        )

        response = requests.get(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 "
                    "(compatible; JobHunterBot/1.0)"
                ),
                "Accept": (
                    "application/xml,text/xml,"
                    "application/rss+xml;q=0.9,*/*;q=0.8"
                ),
            },
            timeout=_TIMEOUT,
        )

        self._check_response(
            response,
            company,
        )

        try:
            root = ET.fromstring(
                response.content
            )
        except ET.ParseError as exc:
            raise RuntimeError(
                f"{company.name}: invalid XML job feed"
            ) from exc

        result: list[dict] = []

        for element in root.iter():
            if self._local_name(
                element.tag
            ) != "job":
                continue

            item: dict[str, str] = {}

            for child in element:
                key = self._local_name(
                    child.tag
                )

                value = (
                    child.text or ""
                ).strip()

                item[key] = value

            if item:
                result.append(item)

        return result

    def parse(
        self,
        raw: list[dict],
        company: Company,
    ) -> list[Job]:
        jobs: list[Job] = []
        seen: set[str] = set()

        for item in raw:
            job = self._parse_item(
                item,
                company,
            )

            if job is None:
                continue

            if job.id in seen:
                continue

            seen.add(job.id)
            jobs.append(job)

        return jobs

    def _parse_item(
        self,
        item: dict,
        company: Company,
    ) -> Job | None:
        job_id = (
            item.get("requisitionid")
            or item.get("referencenumber")
            or item.get("apijobid")
            or ""
        ).strip()

        title = (
            item.get("title")
            or ""
        ).strip()

        url = (
            item.get("url")
            or ""
        ).strip()

        if not job_id or not title or not url:
            return None

        city = (
            item.get("city")
            or ""
        ).strip()

        state = (
            item.get("state")
            or ""
        ).strip()

        country = (
            item.get("country")
            or ""
        ).strip()

        location = ", ".join(
            value
            for value in (
                city,
                state,
                country,
            )
            if value
        )

        if not location:
            location = "Unknown"

        posted_at = self._parse_date(
            item.get("date")
        )

        department = (
            item.get("category")
            or item.get("department")
            or None
        )

        return Job(
            id=job_id,
            title=title,
            company=company.name,
            location=location,
            url=url,
            posted_at=posted_at,
            department=department,
        )

    def _parse_date(
        self,
        value: str | None,
    ) -> datetime | None:
        if not value:
            return None

        try:
            return parsedate_to_datetime(
                value.strip()
            )
        except (
            TypeError,
            ValueError,
        ):
            return None

    def _local_name(
        self,
        tag: str,
    ) -> str:
        return tag.rsplit(
            "}",
            1,
        )[-1].lower()

    def validate(
        self,
        company: Company,
    ) -> bool:
        try:
            jobs = self.fetch_jobs(
                company
            )
        except (
            requests.RequestException,
            RuntimeError,
            ValueError,
        ):
            return False

        return bool(jobs)
