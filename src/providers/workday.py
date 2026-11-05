from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed,
)
import re

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
_DETAIL_WORKERS = 4

_AMBIGUOUS_LOCATION_RE = re.compile(
    r"^\s*\d+\s+Locations?\s*$",
    re.IGNORECASE,
)

class WorkdayAdapter(ProviderAdapter):

    provider_name = "Workday"

    @staticmethod
    def _normalize_detail_location(
        value: str,
        country: str | None,
    ) -> str:
        """Normalize verified Workday location descriptors."""
        value = re.sub(r"\s+", " ", value).strip()

        if not value:
            return ""

        # Baker Hughes-style site identifiers.
        # Apply this only when the detail response confirms India.
        if country == "IN":
            match = re.match(
                r"^IN-(?:MH|Maharashtra)-MUMBAI(?:-|$)",
                value,
                re.I,
            )
            if match:
                return "Mumbai, India"

            match = re.match(
                r"^IN-NAVI[- ]MUMBAI(?:-|$)",
                value,
                re.I,
            )
            if match:
                return "Navi Mumbai, India"

            match = re.match(
                r"^IN-(?:KA|Karnataka)-(?:BANGALORE|BENGALURU)(?:-|$)",
                value,
                re.I,
            )
            if match:
                return "Bengaluru, India"

            match = re.match(
                r"^IN-(?:Maharashtra|MH)-Pune(?:-|$)",
                value,
                re.I,
            )
            if match:
                return "Pune, India"

        # Already human-readable: "Mumbai, India".
        return value

    @classmethod
    def _locations_from_detail(cls, data: dict) -> str | None:
        """Extract actual locations from verified CXS detail fields."""
        info = data.get("jobPostingInfo")

        if not isinstance(info, dict):
            return None

        country_data = info.get("country")
        requisition = info.get("jobRequisitionLocation")

        country_code = None

        if isinstance(requisition, dict):
            requisition_country = requisition.get("country")
            if isinstance(requisition_country, dict):
                country_code = requisition_country.get(
                    "alpha2Code"
                )

        if not country_code and isinstance(country_data, dict):
            descriptor = country_data.get("descriptor")
            if descriptor == "India":
                country_code = "IN"

        locations = []

        primary = info.get("location")
        if isinstance(primary, str) and primary.strip():
            locations.append(primary)

        additional = info.get("additionalLocations") or []

        if isinstance(additional, list):
            locations.extend(
                value
                for value in additional
                if isinstance(value, str) and value.strip()
            )

        normalized = []
        seen = set()

        for value in locations:
            location = cls._normalize_detail_location(
                value,
                country_code,
            )

            key = location.casefold()

            if location and key not in seen:
                seen.add(key)
                normalized.append(location)

        return " | ".join(normalized) if normalized else None

    def _fetch_detail_location(
        self,
        company: Company,
        board: str,
        posting: dict,
    ) -> str | None:
        """Resolve one ambiguous location using public CXS JSON."""
        config = company.provider.config

        external_path = posting.get("externalPath")

        if not isinstance(external_path, str):
            return None

        if not external_path.startswith("/job/"):
            return None

        base = (
            f"https://{config.tenant}."
            f"{config.cluster}.myworkdayjobs.com"
        )

        url = (
            f"{base}/wday/cxs/"
            f"{config.tenant}/{board}"
            f"{external_path}"
        )

        try:
            response = requests.get(
                url,
                headers={
                    "Accept": "application/json",
                    "Referer": f"{base}/en-US/{board}",
                },
                timeout=_TIMEOUT,
            )

            self._check_response(response, company)

            data = response.json()

            if not isinstance(data, dict):
                return None

            return self._locations_from_detail(data)

        except (
            requests.RequestException,
            ValueError,
        ) as exc:
            print(
                "[WORKDAY] LOCATION_DETAIL_FAILED "
                f"company={company.id} "
                f"board={board} "
                f"path={external_path} "
                f"error={type(exc).__name__}"
            )
            return None

    def _enrich_ambiguous_locations(
        self,
        company: Company,
        postings: list[dict],
    ) -> None:
        """Enrich only ambiguous Workday locations in place."""
        candidates = []

        for posting in postings:
            location = str(
                posting.get("locationsText") or ""
            )

            if not _AMBIGUOUS_LOCATION_RE.fullmatch(location):
                continue

            board = posting.get("_workday_board")

            if not board:
                board = company.provider.config.board

            if not board:
                continue

            candidates.append((posting, board))

        if not candidates:
            return

        resolved = 0
        unresolved = 0

        with ThreadPoolExecutor(
            max_workers=_DETAIL_WORKERS
        ) as executor:
            futures = {
                executor.submit(
                    self._fetch_detail_location,
                    company,
                    board,
                    posting,
                ): posting
                for posting, board in candidates
            }

            for future in as_completed(futures):
                posting = futures[future]

                try:
                    location = future.result()
                except Exception as exc:
                    print(
                        "[WORKDAY] LOCATION_ENRICHMENT_ERROR "
                        f"company={company.id} "
                        f"error={type(exc).__name__}"
                    )
                    location = None

                if location:
                    posting["_resolved_location"] = location
                    resolved += 1
                else:
                    unresolved += 1

        print(
            "[WORKDAY] LOCATION_ENRICHMENT "
            f"company={company.id} "
            f"attempted={len(candidates)} "
            f"resolved={resolved} "
            f"unresolved={unresolved}"
        )

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

        boards = list(
            config.boards
        )

        if not boards and config.board:
            boards = [
                config.board
            ]

        if not boards:
            raise ValueError(
                f"{company.name}: Workday requires "
                "config.board or config.boards"
            )

        combined: list[dict] = []

        for board in boards:
            raw = self._fetch_board(
                company,
                board,
            )

            for posting in raw.get(
                "jobPostings",
                [],
            ):
                posting = dict(
                    posting
                )

                posting[
                    "_workday_board"
                ] = board

                combined.append(
                    posting
                )

        deduplicated: list[dict] = []
        seen: set[str] = set()

        for posting in combined:
            key = str(
                posting.get(
                    "externalPath"
                )
                or posting.get(
                    "title"
                )
                or ""
            )

            if key and key in seen:
                continue

            if key:
                seen.add(
                    key
                )

            deduplicated.append(
                posting
            )

        self._enrich_ambiguous_locations(
            company,
            deduplicated,
        )

        return {
            "jobPostings":
                deduplicated
        }

    def _fetch_board(
        self,
        company: Company,
        board: str,
    ) -> dict:
        config = company.provider.config

        tenant = config.tenant
        cluster = config.cluster

        base = (
            f"https://{tenant}."
            f"{cluster}.myworkdayjobs.com"
        )

        url = (
            f"{base}/wday/cxs/"
            f"{tenant}/{board}/jobs"
        )

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

        for item in raw.get(
            "jobPostings",
            [],
        ):
            board = item.get(
                "_workday_board"
            )

            if not board:
                board = config.board

            if not board:
                continue

            job = self._parse_item(
                item=item,
                company=company,
                base_url=base,
                board=board,
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

            location = (
                item.get("_resolved_location")
                or item.get("locationsText")
                or "Unknown"
            )
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

        if (
            not config.tenant
            or not config.cluster
        ):
            return False

        if (
            not config.board
            and not config.boards
        ):
            return False

        boards = list(config.boards)

        if not boards and config.board:
            boards = [config.board]

        for board in boards:
            base = (
                f"https://{config.tenant}."
                f"{config.cluster}.myworkdayjobs.com"
            )

            url = (
                f"{base}/wday/cxs/"
                f"{config.tenant}/{board}/jobs"
            )

            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Origin": base,
                "Referer": f"{base}/en-US/{board}",
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

            if isinstance(data, dict) and (
                "jobPostings" in data or "total" in data
            ):
                return True

        return False