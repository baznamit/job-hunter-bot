import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests

from models import Job
from models.company import Company

from .base import ProviderAdapter
from .exceptions import ProviderTemporaryError, parse_retry_after

_TIMEOUT = 20
_MAX_PAGES = 500

_MAX_RETRIES = 3
_REQUEST_DELAY_SECONDS = 0.35
_RATE_LIMIT_COOLDOWN_SECONDS = 15.0
_BATCH_SIZE = 5
_BATCH_COOLDOWN_SECONDS = 15.0

# Normal Microsoft crawls were observed at 143-271 s. The workflow job times
# out at 15 minutes, so 420 s leaves a wide margin for other companies,
# reporting and state persistence.
_FETCH_BUDGET_SECONDS = 420.0
# Longest server-requested Retry-After that is honored; longer requests are
# deferred to a later run instead of being shortened or slept through.
_MAX_RETRY_AFTER_SECONDS = 60.0
_RETRY_AFTER_MARGIN_SECONDS = 0.5


def _now() -> float:
    return time.monotonic()


class _Deadline:
    """Monotonic budget for one company fetch (never shared across fetches)."""

    def __init__(self, budget_seconds: float) -> None:
        self._expires_at = _now() + budget_seconds

    def remaining(self) -> float:
        return self._expires_at - _now()


def _retry_after_seconds(
    value: str | None,
    now: float | None = None,
) -> float | None:
    """
    Return the server-requested wait, or None when absent or invalid.

    Negative and NaN values are invalid. Infinity is a valid but
    unsatisfiable request. HTTP-dates are handled by the shared parser.
    """
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    try:
        number = float(text)
    except ValueError:
        return parse_retry_after(text, now)

    if math.isnan(number) or number < 0:
        return None

    return parse_retry_after(text, now)


@dataclass
class _InventoryAccounting:
    """Per-fetch aggregate counts; created for each fetch, never shared."""

    pages: int = 0
    raw_records: int = 0
    duplicate_ids: int = 0
    unique_ids: int = 0
    total_first: int | None = None
    total_last: int | None = None
    total_min: int | None = None
    total_max: int | None = None

    def record_page(
        self,
        records: int,
        reported_total: int,
    ) -> None:
        self.pages += 1
        self.raw_records += records

        if self.total_first is None:
            self.total_first = reported_total

        self.total_last = reported_total
        self.total_min = (
            reported_total
            if self.total_min is None
            else min(self.total_min, reported_total)
        )
        self.total_max = (
            reported_total
            if self.total_max is None
            else max(self.total_max, reported_total)
        )


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

    def _deferred_error(
        self,
        company: Company,
        *,
        start: int,
        attempted: bool,
    ) -> ProviderTemporaryError:
        return ProviderTemporaryError(
            company=company.name,
            provider=self.provider_name,
            message=(
                f"deferred reason=time_budget company={company.id} "
                f"operation=listing start={start} "
                f"budget={_FETCH_BUDGET_SECONDS:.0f}s"
            ),
            category="deferred",
            endpoint=self._endpoint(company),
            operation="listing",
            deferral_reason="time_budget",
            deferred_after_attempt=attempted,
        )

    def _ensure_time_for(
        self,
        company: Company,
        deadline: _Deadline,
        needed_seconds: float,
        *,
        start: int,
        attempted: bool,
    ) -> None:
        """Defer instead of waiting when the wait plus a request cannot fit."""
        if needed_seconds >= deadline.remaining():
            raise self._deferred_error(
                company,
                start=start,
                attempted=attempted,
            )

    def _request_page(
        self,
        company: Company,
        *,
        start: int,
        query: str = "",
        deadline: _Deadline | None = None,
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

        if deadline is None:
            deadline = _Deadline(_FETCH_BUDGET_SECONDS)

        for attempt in range(
            _MAX_RETRIES + 1
        ):
            attempted = start > 0 or attempt > 0
            remaining = deadline.remaining()

            if remaining <= 0:
                raise self._deferred_error(
                    company,
                    start=start,
                    attempted=attempted,
                )

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
                timeout=min(
                    _TIMEOUT,
                    remaining,
                ),
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
            requested = _retry_after_seconds(
                retry_after
            )

            if requested is None:
                delay = (
                    _RATE_LIMIT_COOLDOWN_SECONDS
                )
            elif requested > _MAX_RETRY_AFTER_SECONDS:
                # Retrying earlier than requested would defeat the server's
                # limit; waiting this long would stall the whole run.
                raise ProviderTemporaryError(
                    company=company.name,
                    provider=self.provider_name,
                    message=(
                        f"deferred reason=retry_after_exceeds_limit "
                        f"company={company.id} operation=listing "
                        f"start={start} "
                        f"retry_after_seconds={requested:g} "
                        f"limit={_MAX_RETRY_AFTER_SECONDS:g}s"
                    ),
                    status=429,
                    category="rate_limit",
                    retry_after=retry_after,
                    retry_after_seconds=requested,
                    endpoint=response.url,
                    operation="listing",
                    deferral_reason="retry_after_exceeds_limit",
                    deferred_after_attempt=True,
                )
            else:
                # Small safety margin.
                delay = (
                    requested
                    + _RETRY_AFTER_MARGIN_SECONDS
                )

            self._ensure_time_for(
                company,
                deadline,
                delay,
                start=start,
                attempted=True,
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
        accounting = _InventoryAccounting()

        try:
            raw = self._crawl(
                company,
                accounting,
            )
        except Exception:
            self._emit_accounting(
                company,
                accounting,
                status="failed",
            )
            raise

        raw["accounting"] = accounting
        return raw

    def fetch_jobs(
        self,
        company: Company,
    ) -> list[Job]:
        raw = self._fetch_raw(company)
        accounting = raw.get("accounting")

        try:
            jobs, skipped = self._parse_with_skips(
                raw,
                company,
            )
        except Exception:
            self._emit_accounting(
                company,
                accounting,
                status="parse_failed",
            )
            raise

        self._emit_accounting(
            company,
            accounting,
            status="complete",
            jobs=jobs,
            skipped=skipped,
        )
        return jobs

    def _emit_accounting(
        self,
        company: Company,
        accounting: "_InventoryAccounting | None",
        **kwargs,
    ) -> None:
        """Diagnostics must never change or mask a fetch outcome."""
        try:
            print(
                self._accounting_line(
                    company,
                    accounting,
                    **kwargs,
                )
            )
        except Exception:
            pass

    @staticmethod
    def _accounting_line(
        company: Company,
        accounting: "_InventoryAccounting | None",
        *,
        status: str,
        jobs: list[Job] | None = None,
        skipped: dict[str, int] | None = None,
    ) -> str:
        """Aggregate counts and safe category names only; never record data."""
        if accounting is None:
            return (
                f"  [EIGHTFOLD] {company.name}: accounting "
                f"status={status} unavailable"
            )

        line = (
            f"  [EIGHTFOLD] {company.name}: accounting "
            f"status={status} "
            f"pages={accounting.pages} "
            f"raw_records={accounting.raw_records} "
            f"duplicate_ids={accounting.duplicate_ids} "
            f"unique_ids={accounting.unique_ids}"
        )

        if jobs is not None:
            skipped = skipped or {}
            reasons = ",".join(
                f"{reason}:{count}"
                for reason, count in sorted(skipped.items())
            ) or "none"
            line += (
                f" parsed={len(jobs)} "
                f"skipped={sum(skipped.values())} "
                f"skip_reasons={reasons} "
                f"jobs={len(jobs)} "
                f"unique_urls={len({str(job.url) for job in jobs})}"
            )

        def fmt(value: int | None) -> str:
            return "n/a" if value is None else str(value)

        return (
            f"{line} "
            f"total_first={fmt(accounting.total_first)} "
            f"total_last={fmt(accounting.total_last)} "
            f"total_min={fmt(accounting.total_min)} "
            f"total_max={fmt(accounting.total_max)}"
        )

    def _crawl(
        self,
        company: Company,
        accounting: "_InventoryAccounting",
    ) -> dict:
        deadline = _Deadline(
            _FETCH_BUDGET_SECONDS
        )

        first_page, total = self._request_page(
            company,
            start=0,
            deadline=deadline,
        )
        accounting.record_page(
            len(first_page),
            total,
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
                    accounting.duplicate_ids += 1
                    continue

                seen_ids.add(key)
                accounting.unique_ids += 1
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

            self._ensure_time_for(
                company,
                deadline,
                (
                    _BATCH_COOLDOWN_SECONDS
                    if pages_since_cooldown >= _BATCH_SIZE
                    else _REQUEST_DELAY_SECONDS
                ),
                start=offset,
                attempted=True,
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
                deadline=deadline,
            )
            accounting.record_page(
                len(page),
                reported_total,
            )

            if not page:
                category = (
                    "empty_page_after_total_decrease"
                    if reported_total < total
                    else "unexpected_empty_page"
                )
                raise RuntimeError(
                    "Eightfold listing incomplete "
                    f"category={category} "
                    f"company={company.id} start={offset} "
                    f"prior_total={total} count={reported_total}"
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

            # Keep the largest observed boundary so later decreases do not
            # silently shorten the inventory expected from the first page.
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
        return self._parse_with_skips(
            raw,
            company,
        )[0]

    def _parse_with_skips(
        self,
        raw: dict,
        company: Company,
    ) -> tuple[list[Job], dict[str, int]]:
        config = company.provider.config

        positions = (
            raw.get("positions")
            or []
        )

        jobs: list[Job] = []
        skipped: dict[str, int] = {}

        def skip(reason: str) -> None:
            skipped[reason] = skipped.get(reason, 0) + 1

        for item in positions:
            if not isinstance(
                item,
                dict,
            ):
                skip("invalid_record")
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
                if position_id is None:
                    skip("missing_id")
                elif not title:
                    skip("missing_title")
                else:
                    skip("missing_url")
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

        return jobs, skipped

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
