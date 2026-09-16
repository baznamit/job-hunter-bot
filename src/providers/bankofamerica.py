from __future__ import annotations

from datetime import datetime
from urllib.parse import urljoin

import requests

from models import Job
from models.company import Company

from .base import ProviderAdapter

_TIMEOUT = 30
_PAGE_SIZE = 10
_MAX_PAGES = 100

_DEFAULT_BASE_URL = (
    "https://careers.bankofamerica.com"
)

_SEARCH_PATH = (
    "/services/jobssearchservlet"
)


class BankOfAmericaAdapter(
    ProviderAdapter
):
    provider_name = (
        "Bank of America Careers"
    )

    def _base_url(
        self,
        company: Company,
    ) -> str:
        return (
            company.provider.config.base_url
            or _DEFAULT_BASE_URL
        ).rstrip("/")

    def _listing_url(
        self,
        company: Company,
    ) -> str:
        return (
            f"{self._base_url(company)}"
            f"{_SEARCH_PATH}"
        )

    def _headers(
        self,
    ) -> dict[str, str]:
        return {
            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/127.0.0.0 "
                "Safari/537.36"
            ),
            "Accept":
                "application/json",
            "Accept-Language":
                "en-US,en;q=0.9",
        }

    def _request_page(
        self,
        company: Company,
        *,
        start: int,
        rows: int,
    ) -> tuple[list[dict], int]:
        response = requests.get(
            self._listing_url(company),
            params={
                "country": "India",
                "start": start,
                "rows": rows,
                "search":
                    "jobsByCountry",
            },
            headers=self._headers(),
            timeout=_TIMEOUT,
        )

        self._check_response(
            response,
            company,
        )

        try:
            data = response.json()

        except requests.exceptions.JSONDecodeError as exc:
            content_type = (
                response.headers.get(
                    "Content-Type",
                    "unknown",
                )
            )

            body_preview = (
                response.text[:500]
                .replace("\n", " ")
            )

            raise RuntimeError(
                f"{company.name}: "
                "Bank of America API "
                "returned non-JSON response "
                f"(status="
                f"{response.status_code}, "
                f"content_type="
                f"{content_type}, "
                f"url={response.url}, "
                f"body={body_preview!r})"
            ) from exc

        if not isinstance(
            data,
            dict,
        ):
            raise RuntimeError(
                f"{company.name}: "
                "Bank of America API "
                "returned unexpected "
                "response shape"
            )

        jobs = (
            data.get("jobsList")
            or []
        )

        total = data.get(
            "totalMatches"
        )

        if not isinstance(
            jobs,
            list,
        ):
            raise RuntimeError(
                f"{company.name}: "
                "Bank of America jobsList "
                "is not a list"
            )

        if not isinstance(
            total,
            int,
        ):
            raise RuntimeError(
                f"{company.name}: "
                "Bank of America response "
                "is missing totalMatches"
            )

        return jobs, total

    def _fetch_raw(
        self,
        company: Company,
    ) -> dict:
        first_page, total = (
            self._request_page(
                company,
                start=0,
                rows=_PAGE_SIZE,
            )
        )

        all_jobs: list[dict] = []
        seen_ids: set[str] = set()

        def add_page(
            page: list[dict],
        ) -> int:
            added = 0

            for item in page:
                if not isinstance(
                    item,
                    dict,
                ):
                    continue

                job_id = item.get(
                    "jobRequisitionId"
                )

                if job_id is None:
                    continue

                key = str(job_id)

                if key in seen_ids:
                    continue

                seen_ids.add(key)
                all_jobs.append(
                    item
                )
                added += 1

            return added

        add_page(
            first_page
        )

        if total <= len(
            first_page
        ):
            return {
                "jobsList":
                    all_jobs,
            }

        start = len(
            first_page
        )

        page_number = 1

        while start < total:
            if (
                page_number
                >= _MAX_PAGES
            ):
                raise RuntimeError(
                    f"{company.name}: "
                    "Bank of America "
                    "pagination exceeded "
                    f"{_MAX_PAGES} pages"
                )

            # BofA uses rows as the END pointer,
            # not as page size:
            #
            # start=0,  rows=10
            # start=10, rows=20
            # start=20, rows=30
            rows = min(
                start + _PAGE_SIZE,
                total,
            )

            page, reported_total = (
                self._request_page(
                    company,
                    start=start,
                    rows=rows,
                )
            )

            if not page:
                raise RuntimeError(
                    f"{company.name}: "
                    "Bank of America "
                    "pagination ended early "
                    f"at start={start}, "
                    f"rows={rows}, "
                    f"total={total}"
                )

            added = add_page(
                page
            )

            if added == 0:
                raise RuntimeError(
                    f"{company.name}: "
                    "Bank of America "
                    "pagination stalled at "
                    f"start={start}, "
                    f"rows={rows}"
                )

            # Inventory may change while we crawl.
            if (
                isinstance(
                    reported_total,
                    int,
                )
                and reported_total >= 0
            ):
                total = (
                    reported_total
                )

            start = rows
            page_number += 1

        return {
            "jobsList":
                all_jobs,
        }

    @staticmethod
    def _parse_date(
        value: str | None,
    ) -> datetime | None:
        if not value:
            return None

        value = str(
            value
        ).strip()

        # Probe currently exposes dates such
        # as the site's postedDate fields.
        for fmt in (
            "%Y-%m-%d",
            "%m/%d/%Y",
            "%m/%d/%y",
        ):
            try:
                return datetime.strptime(
                    value,
                    fmt,
                )
            except ValueError:
                continue

        try:
            return (
                datetime.fromisoformat(
                    value.replace(
                        "Z",
                        "+00:00",
                    )
                )
            )
        except ValueError:
            return None

    def _job_url(
        self,
        item: dict,
        company: Company,
    ) -> str | None:
        base_url = self._base_url(
            company
        )

        # Prefer the site's explicit external
        # public URL when available.
        for key in (
            "externalUrl",
            "jcrURL",
        ):
            value = item.get(key)

            if value:
                return urljoin(
                    f"{base_url}/",
                    str(value),
                )

        return None

    def parse(
        self,
        raw: dict,
        company: Company,
    ) -> list[Job]:
        jobs: list[Job] = []

        for item in raw.get(
            "jobsList",
            [],
        ):
            if not isinstance(
                item,
                dict,
            ):
                continue

            job_id = item.get(
                "jobRequisitionId"
            )

            title = item.get(
                "postingTitle"
            )

            location = item.get(
                "location"
            )

            url = self._job_url(
                item,
                company,
            )

            if (
                job_id is None
                or not title
                or not url
            ):
                continue

            department = (
                item.get(
                    "careerArea"
                )
                or item.get(
                    "family"
                )
                or item.get(
                    "division"
                )
                or None
            )

            posted_at = (
                self._parse_date(
                    item.get(
                        "postedDate"
                    )
                    or item.get(
                        "externalPostedDate"
                    )
                )
            )

            jobs.append(
                Job(
                    id=str(job_id),
                    title=str(
                        title
                    ).strip(),
                    company=company.name,
                    location=(
                        str(location).strip()
                        if location
                        else "Unknown"
                    ),
                    url=url,
                    posted_at=posted_at,
                    department=department,
                )
            )

        return jobs

    def validate(
        self,
        company: Company,
    ) -> bool:
        jobs, total = (
            self._request_page(
                company,
                start=0,
                rows=1,
            )
        )

        return (
            total >= 0
            and isinstance(
                jobs,
                list,
            )
        )
