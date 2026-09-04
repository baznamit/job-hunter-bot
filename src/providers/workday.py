from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed,
)

import requests

from models import Job
from models.company import Company

from .base import ProviderAdapter

_TIMEOUT = 20
_PAGE_SIZE = 20

# Company-level concurrency is already 6. Keep this deliberately
# conservative so a large Workday board does not create dozens of
# simultaneous requests.
_PAGE_WORKERS = 3

class WorkdayAdapter(ProviderAdapter):

    provider_name = "Workday"

    def _request_page(
        self,
        *,
        url: str,
        headers: dict[str, str],
        offset: int,
        company: Company,
    ) -> dict:
        response = requests.post(
            url,
            json={
                "appliedFacets": {},
                "limit": _PAGE_SIZE,
                "offset": offset,
                "searchText": "",
            },
            headers=headers,
            timeout=_TIMEOUT,
        )

        self._check_response(
            response,
            company,
        )

        data = response.json()

        if not isinstance(data, dict):
            raise ValueError(
                f"{company.name}: Workday returned "
                "a non-object JSON response"
            )

        return data

    def _fetch_raw(
        self,
        company: Company,
    ) -> dict:
        config = company.provider.config

        tenant = config.tenant
        board = config.board
        cluster = config.cluster

        base = f"https://{tenant}.{cluster}.myworkdayjobs.com"
        url = f"{base}/wday/cxs/{tenant}/{board}/jobs"

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Origin": base,
            "Referer": f"{base}/en-US/{board}",
        }

        # Fetch page 1 synchronously. This gives us the
        # authoritative total before scheduling any work.
        first_page = self._request_page(
            url=url,
            headers=headers,
            offset=0,
            company=company,
        )

        first_postings = (
            first_page.get(
                "jobPostings"
            )
            or []
        )

        if not first_postings:
            return {
                "jobPostings": [],
            }

        reported_total = first_page.get(
            "total"
        )

        # Workday normally exposes total on page 1.
        # If it does not, preserve the old sequential
        # behavior rather than making assumptions.
        if (
            not isinstance(
                reported_total,
                int,
            )
            or reported_total <= 0
        ):
            return self._fetch_raw_sequential(
                company=company,
                url=url,
                headers=headers,
                first_postings=first_postings,
            )

        total = reported_total

        if len(first_postings) >= total:
            return {
                "jobPostings":
                    first_postings[:total],
            }

        offsets = list(
            range(
                _PAGE_SIZE,
                total,
                _PAGE_SIZE,
            )
        )

        pages: dict[
            int,
            list[dict],
        ] = {
            0: first_postings,
        }

        with ThreadPoolExecutor(
            max_workers=_PAGE_WORKERS
        ) as executor:

            future_to_offset = {
                executor.submit(
                    self._request_page,
                    url=url,
                    headers=headers,
                    offset=offset,
                    company=company,
                ): offset
                for offset in offsets
            }

            for future in as_completed(
                future_to_offset
            ):
                offset = (
                    future_to_offset[
                        future
                    ]
                )

                data = future.result()

                postings = (
                    data.get(
                        "jobPostings"
                    )
                    or []
                )

                pages[offset] = postings

        # Thread completion order is nondeterministic.
        # Restore Workday's original page ordering.
        all_postings: list[dict] = []

        for offset in sorted(pages):
            all_postings.extend(
                pages[offset]
            )

        # Protect against a board changing while we're
        # crawling it. Deduplicate by externalPath while
        # preserving first occurrence/order.
        deduplicated: list[dict] = []
        seen: set[str] = set()

        for posting in all_postings:
            key = str(
                posting.get(
                    "externalPath"
                )
                or ""
            )

            if key:
                if key in seen:
                    continue

                seen.add(key)

            deduplicated.append(
                posting
            )

        return {
            "jobPostings":
                deduplicated,
        }

    def _fetch_raw_sequential(
        self,
        *,
        company: Company,
        url: str,
        headers: dict[str, str],
        first_postings: list[dict],
    ) -> dict:
        """
        Safe fallback for Workday boards that do not expose
        a usable total on page 1.

        This intentionally retains the previous pagination
        behavior rather than guessing how many pages exist.
        """

        all_postings = list(
            first_postings
        )

        offset = len(
            first_postings
        )

        while True:
            data = self._request_page(
                url=url,
                headers=headers,
                offset=offset,
                company=company,
            )

            postings = (
                data.get(
                    "jobPostings"
                )
                or []
            )

            if not postings:
                break

            all_postings.extend(
                postings
            )

            offset += len(
                postings
            )

        return {
            "jobPostings":
                all_postings,
        }

    def parse(self, raw: dict, company: Company) -> list[Job]:
        config = company.provider.config

        base = (
            f"https://{config.tenant}."
            f"{config.cluster}.myworkdayjobs.com"
        )

        jobs = []

        for item in raw.get("jobPostings", []):
            job = self._parse_item(
                item=item,
                company=company,
                base_url=base,
                board=config.board,
            )

            if job is not None:
                jobs.append(job)

        return jobs

    def _parse_item(
        self,
        item: dict,
        company: Company,
        base_url: str,
        board: str,
    ) -> Job | None:
        try:
            external_path = item.get("externalPath", "")

            # Workday's API returns externalPath without the public
            # career-site board prefix. Build the browser-facing URL
            # using the configured Workday board.
            if external_path:
                external_path = external_path.lstrip("/")
                url = f"{base_url}/en-US/{board}/{external_path}"
            else:
                url = f"{base_url}/en-US/{board}"

            location = item.get("locationsText") or "Unknown"
            department = item.get("businessTitle") or None
            employment_type = item.get("timeType") or None

            return Job(
                id=item.get("externalPath") or item["title"],
                title=item["title"],
                company=company.name,
                location=location,
                url=url,
                posted_at=None,
                department=department,
                employment_type=employment_type,
            )

        except Exception:
            return None

    def validate(self, company: Company) -> bool:
        """
        Validate a Workday tenant/cluster/board using one lightweight
        jobs API request rather than fetching every page.
        """

        config = company.provider.config

        if not config.tenant or not config.cluster or not config.board:
            return False

        base = (
            f"https://{config.tenant}."
            f"{config.cluster}.myworkdayjobs.com"
        )

        url = (
            f"{base}/wday/cxs/"
            f"{config.tenant}/{config.board}/jobs"
        )

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Origin": base,
            "Referer": f"{base}/en-US/{config.board}",
        }

        response = requests.post(
            url,
            json={
                "appliedFacets": {},
                "limit": 1,
                "offset": 0,
                "searchText": "",
            },
            headers=headers,
            timeout=_TIMEOUT,
        )

        self._check_response(response, company)

        data = response.json()

        # A valid Workday jobs endpoint normally returns these fields.
        if not isinstance(data, dict):
            return False

        if "jobPostings" not in data and "total" not in data:
            return False

        return True