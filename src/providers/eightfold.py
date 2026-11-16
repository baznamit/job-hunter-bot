import time
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests

from models import Job
from models.company import Company

from .base import ProviderAdapter

_TIMEOUT = 20
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

        if "positions" not in data:
            raise RuntimeError(
                "Eightfold listing invalid "
                f"category=missing_positions company={company.id} "
                f"start={start}"
            )
        positions = data["positions"]
        if not isinstance(positions, list):
            raise RuntimeError(
                "Eightfold listing invalid "
                f"category=invalid_positions company={company.id} "
                f"start={start} actual={type(positions).__name__}"
            )

        if "count" not in data:
            raise RuntimeError(
                "Eightfold listing invalid "
                f"category=missing_count company={company.id} "
                f"start={start}"
            )
        count = data["count"]
        if (
            isinstance(count, bool)
            or not isinstance(count, int)
            or count < 0
        ):
            raise RuntimeError(
                "Eightfold listing invalid "
                f"category=invalid_count company={company.id} "
                f"start={start} actual={type(count).__name__}"
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
            if total == 0:
                return {"positions": []}
            raise RuntimeError(
                "Eightfold listing contradictory "
                "category=empty_page_with_positive_total "
                f"company={company.id} start=0 count={total}"
            )

        if total < len(first_page):
            raise RuntimeError(
                "Eightfold listing contradictory "
                "category=total_smaller_than_first_page "
                f"company={company.id} start=0 "
                f"count={total} positions={len(first_page)}"
            )

        page_size = len(
            first_page
        )

        all_positions: list[dict] = []
        seen_ids: set[str] = set()
        seen_page_signatures: set[tuple[str, ...]] = set()

        def add_page(
            page: list[dict],
            start: int,
        ) -> int:
            added = 0

            for index, position in enumerate(page):
                if not isinstance(position, dict):
                    raise RuntimeError(
                        "Eightfold listing invalid "
                        f"category=invalid_position company={company.id} "
                        f"start={start} index={index}"
                    )

                position_id = (
                    position.get("id")
                )

                if position_id is None or (
                    isinstance(position_id, str)
                    and not position_id.strip()
                ):
                    raise RuntimeError(
                        "Eightfold listing invalid "
                        f"category=missing_position_id "
                        f"company={company.id} start={start} index={index}"
                    )

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

        add_page(first_page, 0)
        first_signature = tuple(
            str(position["id"])
            for position in first_page
        )
        seen_page_signatures.add(first_signature)

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
                    "Eightfold listing incomplete "
                    f"category=maximum_pages company={company.id} "
                    f"start={offset} max_pages={_MAX_PAGES}"
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
                if reported_total <= offset:
                    # The count can shrink during a crawl. An empty page is
                    # terminal only when its current count is at or before
                    # this offset; otherwise the response is incomplete.
                    break
                raise RuntimeError(
                    "Eightfold listing incomplete "
                    "category=unexpected_empty_page "
                    f"company={company.id} start={offset} "
                    f"count={reported_total}"
                )

            added = add_page(page, offset)
            page_signature = tuple(
                str(position["id"])
                for position in page
            )

            if added == 0:
                category = (
                    "repeated_page"
                    if page_signature in seen_page_signatures
                    else "no_new_positions"
                )
                raise RuntimeError(
                    "Eightfold listing incomplete "
                    f"category={category} company={company.id} "
                    f"start={offset}"
                )
            seen_page_signatures.add(page_signature)

            pages_since_cooldown += 1

            # Keep the largest observed boundary so additions are not
            # silently skipped; a confirmed empty page can terminate a
            # smaller current inventory above.
            total = max(total, reported_total)

            next_offset = offset + len(page)
            if next_offset <= offset:
                raise RuntimeError(
                    "Eightfold listing incomplete "
                    "category=no_forward_progress "
                    f"company={company.id} start={offset}"
                )
            offset = next_offset

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
