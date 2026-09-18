import time
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests

from models import Job
from models.company import Company

from .base import ProviderAdapter

_TIMEOUT = 20
_PAGE_SIZE = 10
_MAX_PAGES = 500

_MAX_RETRIES = 3
_REQUEST_DELAY_SECONDS = 0.35
_RATE_LIMIT_COOLDOWN_SECONDS = 15.0
_BATCH_SIZE = 5
_BATCH_COOLDOWN_SECONDS = 15.0

class EightfoldAdapter(ProviderAdapter):
    """
    Adapter for Eightfold PCS public career search.

    Verified against Microsoft's public PCS endpoint:
        /api/pcsx/search
    """

    provider_name = "Eightfold"

    def _endpoint(
        self,
        company: Company,
    ) -> str:
        config = company.provider.config

        if not config.base_url:
            raise ValueError(
                f"{company.name}: Eightfold requires "
                "config.base_url"
            )

        return (
            f"{config.base_url.rstrip('/')}/"
            "api/pcsx/search"
        )

    def _request_page(
        self,
        company: Company,
        *,
        start: int,
        query: str = "",
    ) -> tuple[list[dict], int]:
        config = company.provider.config

        domain = getattr(
            config,
            "domain",
            None,
        )

        if not domain:
            raise ValueError(
                f"{company.name}: Eightfold requires "
                "config.domain"
            )

        search_location = (
            company.provider.config.search_location
            or ""
        )

        params = {
            "domain": domain,
            "query": query,
            "location": search_location,
            "start": start,
        }

        for attempt in range(
            _MAX_RETRIES + 1
        ):
            response = requests.get(
                self._endpoint(company),
                params=params,
                headers={
                    "Accept":
                        "application/json",
                    "User-Agent": (
                        "Mozilla/5.0 "
                        "(compatible; "
                        "JobHunterBot/1.0)"
                    ),
                },
                timeout=_TIMEOUT,
            )

            if response.status_code != 429:
                break

            if attempt >= _MAX_RETRIES:
                self._check_response(
                    response,
                    company,
                )

            retry_after = (
                response.headers.get(
                    "Retry-After"
                )
            )

            try:
                delay = float(
                    retry_after
                )

                # Small safety margin.
                delay += 0.5

            except (
                TypeError,
                ValueError,
            ):
                delay = (
                    _RATE_LIMIT_COOLDOWN_SECONDS
                )

            print(
                f"  [EIGHTFOLD] "
                f"{company.name}: "
                f"HTTP 429 at start={start}; "
                f"retry {attempt + 1}/"
                f"{_MAX_RETRIES} in "
                f"{delay:.1f}s"
            )

            time.sleep(delay)

        self._check_response(
            response,
            company,
        )

        try:
            payload = response.json()
        except requests.exceptions.JSONDecodeError as exc:
            raise RuntimeError(
                f"{company.name}: Eightfold returned "
                "non-JSON response"
            ) from exc

        if not isinstance(payload, dict):
            raise RuntimeError(
                f"{company.name}: Eightfold returned "
                "unexpected response shape"
            )

        data = payload.get("data")

        if not isinstance(data, dict):
            raise RuntimeError(
                f"{company.name}: Eightfold response "
                "is missing data"
            )

        positions = (
            data.get("positions")
            or []
        )

        count = data.get("count")

        if not isinstance(
            positions,
            list,
        ):
            raise RuntimeError(
                f"{company.name}: Eightfold positions "
                "is not a list"
            )

        if not isinstance(
            count,
            int,
        ):
            count = len(
                positions
            )

        return positions, count

    def _fetch_raw(
        self,
        company: Company,
    ) -> dict:
        first_page, total = self._request_page(
            company,
            start=0,
        )

        if not first_page:
            return {
                "positions": [],
            }

        page_size = len(
            first_page
        )

        if page_size <= 0:
            page_size = _PAGE_SIZE

        all_positions: list[dict] = []
        seen_ids: set[str] = set()

        def add_page(
            page: list[dict],
        ) -> int:
            added = 0

            for position in page:
                if not isinstance(
                    position,
                    dict,
                ):
                    continue

                position_id = (
                    position.get("id")
                )

                if position_id is None:
                    continue

                key = str(
                    position_id
                )

                if key in seen_ids:
                    continue

                seen_ids.add(key)
                all_positions.append(
                    position
                )
                added += 1

            return added

        add_page(
            first_page
        )

        if total <= page_size:
            return {
                "positions":
                    all_positions,
            }

        offset = page_size
        page_number = 1
        pages_since_cooldown = 1

        while offset < total:
            if page_number >= _MAX_PAGES:
                raise RuntimeError(
                    f"{company.name}: Eightfold "
                    "pagination exceeded "
                    f"{_MAX_PAGES} pages"
                )

            if (
                pages_since_cooldown
                >= _BATCH_SIZE
            ):
                print(
                    f"  [EIGHTFOLD] "
                    f"{company.name}: "
                    f"batch cooldown "
                    f"{_BATCH_COOLDOWN_SECONDS:.1f}s "
                    f"after "
                    f"{pages_since_cooldown} pages"
                )

                time.sleep(
                    _BATCH_COOLDOWN_SECONDS
                )

                pages_since_cooldown = 0

            else:
                time.sleep(
                    _REQUEST_DELAY_SECONDS
                )

            page, reported_total = self._request_page(
                company,
                start=offset,
            )

            if not page:
                break

            added = add_page(
                page
            )

            if added == 0:
                raise RuntimeError(
                    f"{company.name}: Eightfold "
                    "pagination stalled at "
                    f"start={offset}"
                )

            pages_since_cooldown += 1

            # Inventory can change while crawling.
            if reported_total > 0:
                total = reported_total

            offset += len(
                page
            )

            page_number += 1

        print(
            f"  [EIGHTFOLD] "
            f"{company.name}: "
            f"pages={page_number}, "
            f"search_location="
            f"{company.provider.config.search_location or 'ALL'}"
        )

        return {
            "positions":
                all_positions,
        }

    @staticmethod
    def _location(
        item: dict,
    ) -> str:
        # Prefer Eightfold's normalized locations:
        # "Bengaluru, KA, IN"
        locations = (
            item.get(
                "standardizedLocations"
            )
            or item.get("locations")
            or []
        )

        if not isinstance(
            locations,
            list,
        ):
            return "Unknown"

        values = [
            str(value).strip()
            for value in locations
            if value
        ]

        return (
            " / ".join(values)
            or "Unknown"
        )

    @staticmethod
    def _posted_at(
        item: dict,
    ) -> datetime | None:
        timestamp = item.get(
            "postedTs"
        )

        if not isinstance(
            timestamp,
            (int, float),
        ):
            return None

        try:
            return datetime.fromtimestamp(
                timestamp,
                tz=timezone.utc,
            )
        except (
            OverflowError,
            OSError,
            ValueError,
        ):
            return None

    def parse(
        self,
        raw: dict,
        company: Company,
    ) -> list[Job]:
        config = company.provider.config

        positions = (
            raw.get("positions")
            or []
        )

        jobs: list[Job] = []

        for item in positions:
            if not isinstance(
                item,
                dict,
            ):
                continue

            position_id = item.get("id")
            title = item.get("name")
            position_url = item.get(
                "positionUrl"
            )

            if (
                position_id is None
                or not title
                or not position_url
            ):
                continue

            url = urljoin(
                f"{config.base_url.rstrip('/')}/",
                str(position_url),
            )

            jobs.append(
                Job(
                    id=str(position_id),
                    title=str(title).strip(),
                    company=company.name,
                    location=self._location(
                        item
                    ),
                    url=url,
                    posted_at=self._posted_at(
                        item
                    ),
                    department=(
                        item.get("department")
                        or None
                    ),
                    employment_type=(
                        item.get(
                            "workLocationOption"
                        )
                        or None
                    ),
                    remote=(
                        str(
                            item.get(
                                "workLocationOption",
                                "",
                            )
                        ).lower()
                        == "remote"
                    ),
                )
            )

        return jobs

    def validate(
        self,
        company: Company,
    ) -> bool:
        positions, total = (
            self._request_page(
                company,
                start=0,
            )
        )

        return (
            total >= 0
            and isinstance(
                positions,
                list,
            )
        )
