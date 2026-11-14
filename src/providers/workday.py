from concurrent.futures import (
    FIRST_COMPLETED,
    ThreadPoolExecutor,
    wait,
)
import re
from urllib.parse import urljoin, urlparse

import requests

from models import Job
from models.company import Company

from .base import ProviderAdapter
from .exceptions import ProviderTemporaryError

_TIMEOUT = 20
_PAGE_SIZE = 20

# Company-level concurrency is already 6. Keep this deliberately
# conservative so a large Workday board does not create dozens of
# simultaneous requests.
_PAGE_WORKERS = 3
_DETAIL_WORKERS = 4
_RESPONSE_PREVIEW_BYTES = 300
_MAINTENANCE_HOST = "community.workday.com"
_MAINTENANCE_PATH = "/maintenance-page"

_AMBIGUOUS_LOCATION_RE = re.compile(
    r"^\s*\d+\s+Locations?\s*$",
    re.IGNORECASE,
)

_SINGLE_LOCATION_CODE_RE = re.compile(
    r"^IN-(?:"
    r"(?:MH|Maharashtra)-MUMBAI(?:-|$)"
    r"|NAVI[- ]MUMBAI(?:-|$)"
    r"|(?:KA|Karnataka)-(?:BANGALORE|BENGALURU)(?:-|$)"
    r"|(?:MH|Maharashtra)-Pune(?:-|$)"
    r")",
    re.IGNORECASE,
)

class WorkdayAdapter(ProviderAdapter):

    provider_name = "Workday"

    @staticmethod
    def _is_maintenance_url(url: str | None) -> bool:
        if not isinstance(url, str) or not url:
            return False

        parsed = urlparse(url)
        return (
            parsed.hostname == _MAINTENANCE_HOST
            and parsed.path.rstrip("/") == _MAINTENANCE_PATH
        )

    @classmethod
    def _is_maintenance_response(cls, response: requests.Response) -> bool:
        urls = [getattr(response, "url", "")]

        history = getattr(response, "history", [])
        if not isinstance(history, (list, tuple)):
            history = []
        for previous in history:
            urls.append(getattr(previous, "url", ""))
            location = getattr(previous, "headers", {}).get("Location")
            if location:
                urls.append(urljoin(previous.url, location))

        return any(cls._is_maintenance_url(url) for url in urls)

    @staticmethod
    def _response_preview(response: requests.Response) -> str:
        content = getattr(response, "content", b"") or b""
        if isinstance(content, bytes):
            content = content[:_RESPONSE_PREVIEW_BYTES].decode(
                getattr(response, "encoding", None) or "utf-8",
                errors="replace",
            )
        return re.sub(r"\s+", " ", str(content))[:_RESPONSE_PREVIEW_BYTES]

    def _validate_json_response(
        self,
        response: requests.Response,
        company: Company,
        *,
        operation: str,
        board: str,
        endpoint: str,
        offset: int | None = None,
        detail_path: str | None = None,
    ) -> dict:
        """Validate a Workday CXS response before decoding or classification."""
        context = (
            f"company={company.id} board={board} operation={operation} "
            f"offset={offset!r} detail_path={detail_path!r} "
            f"original_endpoint={endpoint} status={response.status_code} "
            f"final_url={getattr(response, 'url', '')} "
            f"content_type={getattr(response, 'headers', {}).get('Content-Type', '')!r}"
        )

        if self._is_maintenance_response(response):
            error = ProviderTemporaryError(
                company=company.name,
                provider=self.provider_name,
                message=f"TEMPORARY_MAINTENANCE {context}",
            )
            error.maintenance = True
            raise error

        # Retain ProviderNotFoundError for 404/422 and ProviderTemporaryError
        # for 429/5xx from the common provider classifier.
        self._check_response(response, company)

        try:
            data = response.json()
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Workday invalid JSON ({context}) "
                f"preview={self._response_preview(response)!r}"
            ) from exc

        if not isinstance(data, dict):
            raise ValueError(
                f"Workday unexpected JSON shape ({context}) "
                f"expected=object actual={type(data).__name__}"
            )

        return data

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
            if (
                isinstance(descriptor, str)
                and descriptor.casefold() == "india"
            ):
                country_code = "IN"

        # A conflicting country code must never be interpreted
        # as India, even when the location text begins with IN-.
        if isinstance(country_code, str):
            country_code = country_code.upper()

        if (
            country_code == "IN"
            and isinstance(country_data, dict)
        ):
            descriptor = country_data.get("descriptor")
            if (
                isinstance(descriptor, str)
                and descriptor.strip()
                and descriptor.casefold() != "india"
            ):
                return None

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

            data = self._validate_json_response(
                response,
                company,
                operation="detail_location",
                board=board,
                endpoint=url,
                detail_path=external_path,
            )

            resolved = self._locations_from_detail(data)

            original_location = str(
                posting.get("locationsText") or ""
            ).strip()

            if _SINGLE_LOCATION_CODE_RE.match(original_location):
                info = data.get("jobPostingInfo")

                if not isinstance(info, dict):
                    return None

                requisition = info.get(
                    "jobRequisitionLocation"
                ) or {}

                country = (
                    requisition.get("country")
                    if isinstance(requisition, dict)
                    else None
                )

                alpha2 = (
                    country.get("alpha2Code")
                    if isinstance(country, dict)
                    else None
                )

                descriptor_data = info.get("country")
                descriptor = (
                    descriptor_data.get("descriptor")
                    if isinstance(descriptor_data, dict)
                    else None
                )

                if alpha2 is not None and (
                    not isinstance(alpha2, str)
                    or alpha2.upper() != "IN"
                ):
                    return None

                if descriptor is not None and (
                    not isinstance(descriptor, str)
                    or descriptor.casefold() != "india"
                ):
                    return None

                if not (
                    alpha2 == "IN"
                    or (
                        isinstance(descriptor, str)
                        and descriptor.casefold() == "india"
                    )
                ):
                    return None

            return resolved

        except requests.RequestException as exc:
            raise ProviderTemporaryError(
                company=company.name,
                provider=self.provider_name,
                message=(
                    f"company={company.id} board={board} "
                    f"operation=detail_location detail_path={external_path!r} "
                    f"original_endpoint={url} error={type(exc).__name__}: {exc}"
                ),
            ) from exc

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

            is_multi_location = bool(
                _AMBIGUOUS_LOCATION_RE.fullmatch(location)
            )

            is_site_code = bool(
                _SINGLE_LOCATION_CODE_RE.match(location.strip())
            )

            if not (is_multi_location or is_site_code):
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
        attempted = 0
        failures: dict[str, int] = {}
        next_candidate = 0
        pending = {}
        stop_submitting = False

        def submit_available(executor):
            nonlocal next_candidate
            while (
                not stop_submitting
                and next_candidate < len(candidates)
                and len(pending) < _DETAIL_WORKERS
            ):
                posting, board = candidates[next_candidate]
                next_candidate += 1
                pending[executor.submit(
                    self._fetch_detail_location,
                    company,
                    board,
                    posting,
                )] = posting

        with ThreadPoolExecutor(max_workers=_DETAIL_WORKERS) as executor:
            submit_available(executor)
            while pending:
                done, _ = wait(
                    pending,
                    return_when=FIRST_COMPLETED,
                )
                for future in done:
                    posting = pending.pop(future)
                    attempted += 1
                    try:
                        location = future.result()
                    except Exception as exc:
                        location = None
                        reason = type(exc).__name__
                        if isinstance(exc, ProviderTemporaryError):
                            status = re.search(r"\bstatus=(\d+)\b", str(exc))
                            if status:
                                reason += f"/{status.group(1)}"
                            stop_submitting = True
                        failures[reason] = failures.get(reason, 0) + 1

                    if location:
                        posting["_resolved_location"] = location
                        resolved += 1
                    else:
                        unresolved += 1

                if stop_submitting:
                    for future in pending:
                        future.cancel()
                    pending.clear()
                else:
                    submit_available(executor)

        unattempted = len(candidates) - attempted

        print(
            "[WORKDAY] LOCATION_ENRICHMENT "
            f"company={company.id} "
            f"attempted={attempted} "
            f"resolved={resolved} "
            f"unresolved={unresolved} "
            f"failed={sum(failures.values())} "
            f"unattempted={unattempted} "
            f"failure_reasons={failures}"
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

        data = self._validate_json_response(
            response,
            company,
            operation="listing",
            board=headers["Referer"].rsplit("/", 1)[-1],
            endpoint=url,
            offset=offset,
        )

        postings = data.get("jobPostings")
        if postings is not None and not isinstance(postings, list):
            raise ValueError(
                f"Workday unexpected listing shape company={company.id} "
                f"board={headers['Referer'].rsplit('/', 1)[-1]} "
                f"offset={offset} expected=jobPostings-list "
                f"actual={type(postings).__name__} "
                f"original_endpoint={url}"
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

        next_offset = iter(offsets)
        pending = {}
        failure = None

        with ThreadPoolExecutor(max_workers=_PAGE_WORKERS) as executor:
            for _ in range(_PAGE_WORKERS):
                try:
                    offset = next(next_offset)
                except StopIteration:
                    break
                pending[executor.submit(
                    self._request_page,
                    url=url,
                    headers=headers,
                    offset=offset,
                    company=company,
                )] = offset

            while pending and failure is None:
                done, _ = wait(
                    pending,
                    return_when=FIRST_COMPLETED,
                )
                for future in done:
                    offset = pending.pop(future)
                    try:
                        data = future.result()
                    except Exception as exc:
                        failure = exc
                        break

                    postings = data.get("jobPostings") or []
                    pages[offset] = postings

                if failure is not None:
                    for future in pending:
                        future.cancel()
                    pending.clear()
                    break

                while len(pending) < _PAGE_WORKERS:
                    try:
                        offset = next(next_offset)
                    except StopIteration:
                        break
                    pending[executor.submit(
                        self._request_page,
                        url=url,
                        headers=headers,
                        offset=offset,
                        company=company,
                    )] = offset

        if failure is not None:
            # Do not return a partial inventory when a later page fails.
            raise failure

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

            data = self._validate_json_response(
                response,
                company,
                operation="validation",
                board=board,
                endpoint=url,
                offset=0,
            )

            if (
                "jobPostings" not in data
                or isinstance(data.get("jobPostings"), list)
            ) and ("jobPostings" in data or "total" in data):
                return True

        return False
