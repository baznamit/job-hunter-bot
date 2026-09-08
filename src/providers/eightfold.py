from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed,
)
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests

from models import Job
from models.company import Company

from .base import ProviderAdapter

_TIMEOUT = 20
_PAGE_SIZE = 10
_PAGE_WORKERS = 3
_MAX_PAGES = 500

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

        response = requests.get(
            self._endpoint(company),
            params={
                "domain": domain,
                "query": query,
                "location": "",
                "start": start,
            },
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

        if not isinstance(count, int):
            count = len(positions)

        return positions, count

    def _fetch_raw(
        self,
        company: Company,
    ) -> dict:
        first_page, total = (
            self._request_page(
                company,
                start=0,
            )
        )

        if not first_page:
            return {
                "positions": [],
            }

        if total <= len(first_page):
            return {
                "positions": first_page,
            }

        page_size = len(first_page)

        if page_size <= 0:
            page_size = _PAGE_SIZE

        offsets = list(
            range(
                page_size,
                total,
                page_size,
            )
        )

        if len(offsets) >= _MAX_PAGES:
            raise RuntimeError(
                f"{company.name}: Eightfold "
                f"pagination exceeded {_MAX_PAGES} pages"
            )

        pages: dict[
            int,
            list[dict],
        ] = {
            0: first_page,
        }

        with ThreadPoolExecutor(
            max_workers=_PAGE_WORKERS
        ) as executor:
            future_offsets = {
                executor.submit(
                    self._request_page,
                    company,
                    start=offset,
                ): offset
                for offset in offsets
            }

            for future in as_completed(
                future_offsets
            ):
                offset = future_offsets[
                    future
                ]

                positions, _ = (
                    future.result()
                )

                pages[offset] = positions

        positions: list[dict] = []
        seen_ids: set[str] = set()

        for offset in sorted(pages):
            page = pages[offset]

            previous_count = len(
                seen_ids
            )

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

                key = str(position_id)

                if key in seen_ids:
                    continue

                seen_ids.add(key)
                positions.append(position)

            # Protect against an endpoint ignoring `start`
            # and repeatedly returning page 1.
            if (
                offset > 0
                and page
                and len(seen_ids)
                == previous_count
            ):
                raise RuntimeError(
                    f"{company.name}: Eightfold "
                    "pagination stalled at "
                    f"start={offset}"
                )

        return {
            "positions": positions,
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
