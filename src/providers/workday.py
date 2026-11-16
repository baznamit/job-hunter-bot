from concurrent.futures import (
    FIRST_COMPLETED,
    ThreadPoolExecutor,
    wait,
)
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
import math
import re
from threading import Lock, local
import time
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
_REQUEST_PACING_SECONDS = 0.2
_MAX_REQUEST_ATTEMPTS = 2
_COMPANY_RECOVERY_BUDGET_SECONDS = 120.0
_BACKOFF_SECONDS = (1.0, 3.0)
_RESPONSE_PREVIEW_BYTES = 300
_MAINTENANCE_HOST = "community.workday.com"
_MAINTENANCE_PATH = "/maintenance-page"


def _is_finite_number(value) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


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


@dataclass
class WorkdayCoverageReport:
    """Coverage counts; deferrals overlap candidate outcomes, not extra candidates."""

    listing_status: str = "complete"
    enrichment_candidates: int = 0
    enrichment_attempted: int = 0
    enrichment_resolved: int = 0
    enrichment_unresolved: int = 0
    enrichment_unstarted: int = 0
    http_attempts: int = 0
    http_retries: int = 0
    failure_reasons: dict[str, int] = field(default_factory=dict)
    deferred: int = 0
    deferred_before_attempt: int = 0
    deferred_after_attempt: int = 0
    deferral_reasons: dict[str, int] = field(default_factory=dict)
    stop_reason: str | None = None

    @property
    def coverage_status(self) -> str:
        if self.listing_status != "complete":
            return "failed"
        if self.enrichment_candidates and (
            self.enrichment_unresolved or self.enrichment_unstarted
        ):
            return "partial"
        return "complete"


@dataclass(frozen=True)
class _PolicyDecision:
    allowed: bool
    reason: str | None = None


@dataclass
class _HostCoordination:
    waiters: list[object] = field(default_factory=list)
    last_dispatch: float | None = None
    cooldown_until: float = 0.0
    blocked: str | None = None


class WorkdayRequestPolicy:
    """Coordinate bounded Workday pacing and host cooldowns."""

    def __init__(
        self,
        *,
        pacing_seconds: float = _REQUEST_PACING_SECONDS,
        max_attempts: int = _MAX_REQUEST_ATTEMPTS,
        backoff_seconds: tuple[float, ...] = _BACKOFF_SECONDS,
        company_budget_seconds: float = _COMPANY_RECOVERY_BUDGET_SECONDS,
        clock=time.monotonic,
        sleeper=time.sleep,
    ) -> None:
        if not _is_finite_number(pacing_seconds) or pacing_seconds < 0:
            raise ValueError("Workday pacing_seconds must be finite and nonnegative")
        if (
            isinstance(max_attempts, bool)
            or not isinstance(max_attempts, int)
            or max_attempts < 1
        ):
            raise ValueError("Workday max_attempts must be a positive integer")
        if (
            not _is_finite_number(company_budget_seconds)
            or company_budget_seconds <= 0
        ):
            raise ValueError(
                "Workday company_budget_seconds must be finite and positive"
            )
        if not isinstance(backoff_seconds, (tuple, list)) or not backoff_seconds:
            raise ValueError("Workday backoff_seconds must be a non-empty sequence")
        if any(
            not _is_finite_number(delay) or delay < 0
            for delay in backoff_seconds
        ):
            raise ValueError(
                "Workday backoff_seconds values must be finite and nonnegative"
            )
        self.pacing_seconds = pacing_seconds
        self.max_attempts = max_attempts
        self.backoff_seconds = tuple(backoff_seconds)
        self.company_budget_seconds = company_budget_seconds
        self._clock = clock
        self._sleep = sleeper
        self._lock = Lock()
        self._hosts: dict[str, _HostCoordination] = {}

    @classmethod
    def from_settings(cls, settings: dict | None) -> "WorkdayRequestPolicy":
        if settings is None:
            settings = {}
        if not isinstance(settings, dict):
            raise ValueError("settings.workday must be an object")

        known = {
            "request_pacing_seconds": "pacing_seconds",
            "max_attempts": "max_attempts",
            "company_budget_seconds": "company_budget_seconds",
            "backoff_seconds": "backoff_seconds",
        }
        values = {
            target: settings[key]
            for key, target in known.items()
            if key in settings
        }
        return cls(**values)

    def monotonic(self) -> float:
        return self._clock()

    @staticmethod
    def retry_after_seconds(value: str | None, now: float | None = None) -> float | None:
        if not value:
            return None
        try:
            return max(0.0, float(value))
        except (TypeError, ValueError):
            pass

        try:
            retry_at = parsedate_to_datetime(value)
            if retry_at.tzinfo is None:
                return None
            current = time.time() if now is None else now
            return max(0.0, retry_at.timestamp() - current)
        except (TypeError, ValueError, OverflowError):
            return None

    def before_request(self, host: str, deadline: float | None) -> _PolicyDecision:
        with self._lock:
            state = self._hosts.setdefault(host, _HostCoordination())
            ticket = object()
            state.waiters.append(ticket)

        while True:
            with self._lock:
                state = self._hosts[host]
                if state.blocked:
                    state.waiters.remove(ticket)
                    return _PolicyDecision(False, state.blocked)

                now = self._clock()
                if deadline is not None and now >= deadline:
                    state.waiters.remove(ticket)
                    return _PolicyDecision(False, "time_budget")

                position = state.waiters.index(ticket)
                eligible_at = max(now, state.cooldown_until)
                if state.last_dispatch is not None:
                    eligible_at = max(
                        eligible_at,
                        state.last_dispatch + self.pacing_seconds,
                    )
                eligible_at += position * self.pacing_seconds

                if deadline is not None and eligible_at > deadline:
                    state.waiters.remove(ticket)
                    return _PolicyDecision(False, "time_budget")

                if position == 0 and now >= eligible_at:
                    state.waiters.pop(0)
                    state.last_dispatch = now
                    return _PolicyDecision(True)

                delay = max(0.0, eligible_at - now)

            self._sleep(delay)

    def after_failure(
        self,
        host: str,
        error: ProviderTemporaryError,
        attempt: int,
    ) -> None:
        if error.category in {"maintenance", "access_challenge"}:
            with self._lock:
                state = self._hosts.setdefault(host, _HostCoordination())
                state.blocked = error.category
            return

        delay = error.retry_after_seconds
        if delay is None:
            delay = self.backoff_seconds[
                min(max(attempt - 1, 0), len(self.backoff_seconds) - 1)
            ]

        with self._lock:
            state = self._hosts.setdefault(host, _HostCoordination())
            state.cooldown_until = max(
                state.cooldown_until,
                self._clock() + max(0.0, delay),
            )


class _RequestStats:
    def __init__(self) -> None:
        self.attempts = 0
        self.retries = 0

class WorkdayAdapter(ProviderAdapter):

    provider_name = "Workday"

    def __init__(self, request_policy: WorkdayRequestPolicy | None = None) -> None:
        self._request_policy = request_policy or WorkdayRequestPolicy()
        self._request_stats = local()

    def _current_request_stats(self) -> _RequestStats | None:
        return getattr(self._request_stats, "value", None)

    def _run_detail_candidate(
        self,
        company: Company,
        board: str,
        posting: dict,
        deadline: float | None,
    ):
        stats = _RequestStats()
        self._request_stats.value = stats
        self._request_stats.deadline = deadline
        try:
            return self._fetch_detail_location(
                company,
                board,
                posting,
            ), stats
        except Exception as exc:
            exc._workday_stats = stats
            raise
        finally:
            self._request_stats.value = None
            self._request_stats.deadline = None

    def _request_json(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        payload: dict | None,
        company: Company,
        board: str,
        operation: str,
        offset: int | None = None,
        detail_path: str | None = None,
        deadline: float | None = None,
    ) -> dict:
        parsed_url = urlparse(url)
        host = parsed_url.hostname or parsed_url.netloc
        stats = self._current_request_stats()
        last_error = None

        for attempt in range(1, self._request_policy.max_attempts + 1):
            decision = self._request_policy.before_request(host, deadline)
            if not decision.allowed:
                raise ProviderTemporaryError(
                    company=company.name,
                    provider=self.provider_name,
                    message=(
                        f"deferred reason={decision.reason} company={company.id} "
                        f"board={board} operation={operation} "
                        f"endpoint={url}"
                    ),
                    category="deferred",
                    endpoint=url,
                    operation=operation,
                    deferral_reason=decision.reason,
                    deferred_after_attempt=bool(
                        stats is not None and stats.attempts
                    ),
                )

            try:
                request = getattr(requests, method)
                kwargs = {
                    "headers": headers,
                    "timeout": _TIMEOUT,
                }
                if payload is not None:
                    kwargs["json"] = payload
                if stats is not None:
                    stats.attempts += 1
                    if stats.attempts > 1:
                        stats.retries += 1
                response = request(url, **kwargs)
            except requests.Timeout as exc:
                last_error = ProviderTemporaryError(
                    company=company.name,
                    provider=self.provider_name,
                    message=(
                        f"timeout company={company.id} board={board} "
                        f"operation={operation} endpoint={url}"
                    ),
                    category="timeout",
                    endpoint=url,
                    operation=operation,
                )
            except requests.ConnectionError as exc:
                last_error = ProviderTemporaryError(
                    company=company.name,
                    provider=self.provider_name,
                    message=(
                        f"connection_error company={company.id} board={board} "
                        f"operation={operation} endpoint={url}"
                    ),
                    category="connection_error",
                    endpoint=url,
                    operation=operation,
                )
            except requests.RequestException as exc:
                last_error = ProviderTemporaryError(
                    company=company.name,
                    provider=self.provider_name,
                    message=(
                        f"request_error company={company.id} board={board} "
                        f"operation={operation} endpoint={url}"
                    ),
                    category="connection_error",
                    endpoint=url,
                    operation=operation,
                )
            else:
                try:
                    return self._validate_json_response(
                        response,
                        company,
                        operation=operation,
                        board=board,
                        endpoint=url,
                        offset=offset,
                        detail_path=detail_path,
                    )
                except ProviderTemporaryError as exc:
                    if exc.endpoint is None:
                        exc.endpoint = url
                    if exc.operation is None:
                        exc.operation = operation
                    last_error = exc
                except ValueError:
                    raise

            if last_error is None:
                break
            if last_error.retry_after_seconds is None:
                last_error.retry_after_seconds = (
                    self._request_policy.retry_after_seconds(
                        last_error.retry_after
                    )
                )
            if last_error.category in {"maintenance", "access_challenge"}:
                self._request_policy.after_failure(host, last_error, attempt)
                raise last_error
            self._request_policy.after_failure(host, last_error, attempt)
            if attempt >= self._request_policy.max_attempts:
                break

        raise last_error

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
                status=response.status_code,
                category="maintenance",
                retry_after=response.headers.get("Retry-After"),
                endpoint=endpoint,
                operation=operation,
            )
            error.maintenance = True
            raise error

        if response.status_code == 403:
            raise ProviderTemporaryError(
                company=company.name,
                provider=self.provider_name,
                message=f"ACCESS_CHALLENGE {context}",
                status=response.status_code,
                category="access_challenge",
                endpoint=endpoint,
                operation=operation,
            )

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
        *,
        deadline: float | None = None,
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

        if deadline is None:
            deadline = getattr(self._request_stats, "deadline", None)

        try:
            data = self._request_json(
                method="get",
                url=url,
                headers={
                    "Accept": "application/json",
                    "Referer": f"{base}/en-US/{board}",
                },
                payload=None,
                company=company,
                board=board,
                operation="detail_location",
                detail_path=external_path,
                deadline=deadline,
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
        *,
        deadline: float | None = None,
    ) -> WorkdayCoverageReport:
        """Enrich only ambiguous Workday locations in place."""
        report = WorkdayCoverageReport()
        candidates = []
        seen_candidates = set()

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

            external_path = posting.get("externalPath")
            candidate_key = (
                ("path", external_path)
                if isinstance(external_path, str) and external_path
                else ("object", id(posting))
            )
            if candidate_key in seen_candidates:
                continue
            seen_candidates.add(candidate_key)
            candidates.append((posting, board))

        report.enrichment_candidates = len(candidates)
        if not candidates:
            return report

        failures: dict[str, int] = {}
        deferral_reasons: dict[str, int] = {}
        deferred_before_attempt = 0
        deferred_after_attempt = 0
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
                    self._run_detail_candidate,
                    company,
                    board,
                    posting,
                    deadline,
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
                    had_error = False
                    try:
                        result = future.result()
                        if isinstance(result, tuple):
                            location, stats = result
                        else:
                            location, stats = result, None
                    except Exception as exc:
                        had_error = True
                        location = None
                        stats = getattr(exc, "_workday_stats", None)
                        reason = type(exc).__name__
                        if isinstance(exc, ProviderTemporaryError):
                            reason = exc.category or reason
                            if exc.status is not None:
                                reason += f"/{exc.status}"
                            if exc.category == "deferred":
                                cause = exc.deferral_reason or "unknown"
                                after_attempt = bool(
                                    stats is not None and stats.attempts
                                )
                                phase = (
                                    "after_attempt"
                                    if after_attempt
                                    else "before_attempt"
                                )
                                deferral_key = f"{phase}:{cause}"
                                deferral_reasons[deferral_key] = (
                                    deferral_reasons.get(deferral_key, 0) + 1
                                )
                                if after_attempt:
                                    deferred_after_attempt += 1
                                else:
                                    deferred_before_attempt += 1
                                report.stop_reason = cause
                                stop_submitting = True
                            elif exc.category in {
                                "maintenance",
                                "access_challenge",
                            } or getattr(exc, "maintenance", False):
                                stop_reason = (
                                    "maintenance"
                                    if getattr(exc, "maintenance", False)
                                    else exc.category
                                )
                                if getattr(exc, "maintenance", False):
                                    reason = "maintenance"
                                report.stop_reason = stop_reason
                                stop_submitting = True
                        failures[reason] = failures.get(reason, 0) + 1

                    if stats is not None:
                        report.http_attempts += stats.attempts
                        report.http_retries += stats.retries

                    candidate_attempted = bool(
                        stats is not None and stats.attempts
                    )
                    if candidate_attempted and location:
                        posting["_resolved_location"] = location
                        report.enrichment_resolved += 1
                    elif candidate_attempted:
                        report.enrichment_unresolved += 1
                        if not had_error:
                            failures["no_usable_location"] = (
                                failures.get("no_usable_location", 0) + 1
                            )

                if stop_submitting:
                    for future in list(pending):
                        if future.cancel():
                            pending.pop(future, None)
                else:
                    submit_available(executor)

        report.enrichment_attempted = (
            report.enrichment_resolved + report.enrichment_unresolved
        )
        report.enrichment_unstarted = (
            report.enrichment_candidates - report.enrichment_attempted
        )
        report.failure_reasons = failures
        report.deferred_before_attempt = deferred_before_attempt
        report.deferred_after_attempt = deferred_after_attempt
        report.deferral_reasons = deferral_reasons
        report.deferred = deferred_before_attempt + deferred_after_attempt

        print(
            "[WORKDAY] LOCATION_ENRICHMENT "
            f"company={company.id} "
            f"attempted={report.enrichment_attempted} "
            f"resolved={report.enrichment_resolved} "
            f"unresolved={report.enrichment_unresolved} "
            f"failed={sum(failures.values())} "
            f"unstarted={report.enrichment_unstarted} "
            f"http_attempts={report.http_attempts} "
            f"http_retries={report.http_retries} "
            f"failure_reasons={failures} "
            f"deferral_reasons={deferral_reasons} "
            f"stop_reason={report.stop_reason}"
        )
        return report

    def _request_page(
        self,
        *,
        url: str,
        headers: dict[str, str],
        offset: int,
        company: Company,
        deadline: float | None = None,
    ) -> dict:
        data = self._request_json(
            method="post",
            url=url,
            payload={
                "appliedFacets": {},
                "limit": _PAGE_SIZE,
                "offset": offset,
                "searchText": "",
            },
            headers=headers,
            company=company,
            board=headers["Referer"].rsplit("/", 1)[-1],
            operation="listing",
            offset=offset,
            deadline=deadline,
        )
        board = headers["Referer"].rsplit("/", 1)[-1]
        if "jobPostings" not in data:
            raise ValueError(
                "Workday listing invalid "
                f"category=missing_job_postings company={company.id} "
                f"board={board} offset={offset}"
            )
        postings = data["jobPostings"]
        if not isinstance(postings, list):
            raise ValueError(
                "Workday listing invalid "
                f"category=invalid_job_postings company={company.id} "
                f"board={board} offset={offset} "
                f"actual={type(postings).__name__}"
            )
        return data

    def _run_page_request(
        self,
        *,
        url: str,
        headers: dict[str, str],
        offset: int,
        company: Company,
        deadline: float | None,
    ):
        stats = _RequestStats()
        self._request_stats.value = stats
        try:
            return self._request_page(
                url=url,
                headers=headers,
                offset=offset,
                company=company,
                deadline=deadline,
            ), stats
        except Exception as exc:
            exc._workday_stats = stats
            raise
        finally:
            self._request_stats.value = None

    @staticmethod
    def _merge_enrichment_report(
        target: WorkdayCoverageReport,
        source: WorkdayCoverageReport,
    ) -> None:
        target.enrichment_candidates += source.enrichment_candidates
        target.enrichment_attempted += source.enrichment_attempted
        target.enrichment_resolved += source.enrichment_resolved
        target.enrichment_unresolved += source.enrichment_unresolved
        target.enrichment_unstarted += source.enrichment_unstarted
        target.http_attempts += source.http_attempts
        target.http_retries += source.http_retries
        target.deferred += source.deferred
        target.deferred_before_attempt += source.deferred_before_attempt
        target.deferred_after_attempt += source.deferred_after_attempt
        if source.stop_reason:
            target.stop_reason = source.stop_reason
        for reason, count in source.failure_reasons.items():
            target.failure_reasons[reason] = (
                target.failure_reasons.get(reason, 0) + count
            )
        for reason, count in source.deferral_reasons.items():
            target.deferral_reasons[reason] = (
                target.deferral_reasons.get(reason, 0) + count
            )

    def fetch_jobs_with_report(
        self,
        company: Company,
    ) -> tuple[list[Job], WorkdayCoverageReport]:
        report = WorkdayCoverageReport()
        deadline = (
            self._request_policy.monotonic()
            + self._request_policy.company_budget_seconds
        )
        try:
            raw = self._fetch_raw(
                company,
                report=report,
                deadline=deadline,
            )
        except Exception as exc:
            report.listing_status = "failed"
            if (
                isinstance(exc, ProviderTemporaryError)
                and exc.category == "deferred"
            ):
                after_attempt = bool(exc.deferred_after_attempt)
                phase = (
                    "after_attempt"
                    if after_attempt
                    else "before_attempt"
                )
                reason = exc.deferral_reason or "unknown"
                key = f"{phase}:{reason}"
                report.deferred = 1
                report.deferred_after_attempt = int(after_attempt)
                report.deferred_before_attempt = int(not after_attempt)
                report.deferral_reasons[key] = 1
                report.stop_reason = reason
            exc.workday_report = report
            raise
        try:
            jobs = self.parse(raw, company)
        except Exception as exc:
            exc.workday_report = report
            raise
        return jobs, report

    def _fetch_raw(
        self,
        company: Company,
        *,
        report: WorkdayCoverageReport | None = None,
        deadline: float | None = None,
    ) -> dict:
        report = report or WorkdayCoverageReport()
        if deadline is None:
            deadline = (
                self._request_policy.monotonic()
                + self._request_policy.company_budget_seconds
            )
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
                report=report,
                deadline=deadline,
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

        enrichment = self._enrich_ambiguous_locations(
            company,
            deduplicated,
            deadline=deadline,
        )
        self._merge_enrichment_report(report, enrichment)

        return {
            "jobPostings":
                deduplicated
        }

    def _fetch_board(
        self,
        company: Company,
        board: str,
        *,
        report: WorkdayCoverageReport | None = None,
        deadline: float | None = None,
    ) -> dict:
        report = report or WorkdayCoverageReport()
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
        try:
            first_page, first_stats = self._run_page_request(
                url=url,
                headers=headers,
                offset=0,
                company=company,
                deadline=deadline,
            )
        except Exception as exc:
            first_stats = getattr(exc, "_workday_stats", None)
            if first_stats is not None:
                report.http_attempts += first_stats.attempts
                report.http_retries += first_stats.retries
            raise
        report.http_attempts += first_stats.attempts
        report.http_retries += first_stats.retries

        first_postings = (
            first_page["jobPostings"]
        )

        if "total" not in first_page:
            if not first_postings:
                raise ValueError(
                    "Workday listing incomplete "
                    "category=missing_total_for_empty_inventory "
                    f"company={company.id} board={board} offset=0"
                )
            if len(first_postings) > _PAGE_SIZE:
                raise ValueError(
                    "Workday listing invalid "
                    "category=first_page_exceeds_limit "
                    f"company={company.id} board={board} offset=0 "
                    f"limit={_PAGE_SIZE} actual={len(first_postings)}"
                )
            # Only an absent total opts into the supported sequential
            # fallback; explicit null or malformed totals are errors.
            return self._fetch_raw_sequential(
                company=company,
                url=url,
                headers=headers,
                first_postings=first_postings,
                report=report,
                deadline=deadline,
            )

        reported_total = first_page["total"]
        if (
            isinstance(reported_total, bool)
            or not isinstance(reported_total, int)
            or reported_total < 0
        ):
            raise ValueError(
                "Workday listing invalid category=invalid_total "
                f"company={company.id} board={board} offset=0 "
                f"actual={type(reported_total).__name__}"
            )

        if not first_postings:
            if reported_total == 0:
                return {"jobPostings": []}
            raise ValueError(
                "Workday listing contradictory "
                "category=empty_page_with_positive_total "
                f"company={company.id} board={board} offset=0 "
                f"total={reported_total}"
            )

        if reported_total < len(first_postings):
            raise ValueError(
                "Workday listing contradictory "
                "category=total_smaller_than_first_page "
                f"company={company.id} board={board} offset=0 "
                f"total={reported_total} postings={len(first_postings)}"
            )

        if len(first_postings) > _PAGE_SIZE:
            raise ValueError(
                "Workday listing invalid "
                "category=first_page_exceeds_limit "
                f"company={company.id} board={board} offset=0 "
                f"limit={_PAGE_SIZE} actual={len(first_postings)}"
            )

        total = reported_total
        # Use page 0 as the inventory boundary. Later totals are not
        # authoritative; returned page lengths are checked against this
        # boundary. Additions after page 0 may not be included.
        expected_first_count = min(total, _PAGE_SIZE)
        if len(first_postings) < expected_first_count:
            raise ValueError(
                "Workday listing incomplete category=short_first_page "
                f"company={company.id} board={board} offset=0 "
                f"expected_at_least={expected_first_count} "
                f"actual={len(first_postings)} total={total}"
            )

        if len(first_postings) == total:
            return {
                "jobPostings":
                    first_postings,
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
                    self._run_page_request,
                    url=url,
                    headers=headers,
                    offset=offset,
                    company=company,
                    deadline=deadline,
                )] = offset

            while pending:
                done, _ = wait(
                    pending,
                    return_when=FIRST_COMPLETED,
                )
                for future in done:
                    offset = pending.pop(future)
                    try:
                        data, stats = future.result()
                    except Exception as exc:
                        stats = getattr(exc, "_workday_stats", None)
                        if stats is not None:
                            report.http_attempts += stats.attempts
                            report.http_retries += stats.retries
                        if failure is None:
                            failure = exc
                        continue

                    report.http_attempts += stats.attempts
                    report.http_retries += stats.retries

                    if failure is None:
                        postings = data["jobPostings"]
                        expected_count = min(
                            _PAGE_SIZE,
                            total - offset,
                        )
                        if not postings:
                            failure = ValueError(
                                "Workday listing incomplete "
                                "category=unexpected_empty_page "
                                f"company={company.id} board={board} "
                                f"offset={offset} total={total}"
                            )
                        elif len(postings) < expected_count:
                            failure = ValueError(
                                "Workday listing incomplete "
                                "category=short_page "
                                f"company={company.id} board={board} "
                                f"offset={offset} "
                                f"expected_at_least={expected_count} "
                                f"actual={len(postings)} total={total}"
                            )
                        else:
                            pages[offset] = postings

                if failure is not None:
                    for future in list(pending):
                        if future.cancel():
                            pending.pop(future, None)
                    continue

                while len(pending) < _PAGE_WORKERS:
                    try:
                        offset = next(next_offset)
                    except StopIteration:
                        break
                    pending[executor.submit(
                        self._run_page_request,
                        url=url,
                        headers=headers,
                        offset=offset,
                        company=company,
                        deadline=deadline,
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
        report: WorkdayCoverageReport | None = None,
        deadline: float | None = None,
    ) -> dict:
        """
        Safe fallback for Workday boards that do not expose
        a usable total on page 1.

        The existing company request deadline bounds this crawl. Empty
        terminal pages remain valid, while repeated pages and pages with
        no new posting identities fail instead of looping indefinitely.
        """

        report = report or WorkdayCoverageReport()
        if deadline is None:
            deadline = (
                self._request_policy.monotonic()
                + self._request_policy.company_budget_seconds
            )
        all_postings = list(
            first_postings
        )

        def posting_identity(posting: dict) -> str:
            return str(
                posting.get("externalPath")
                or posting.get("title")
                or repr(posting)
            )

        seen_posting_ids = {
            posting_identity(posting)
            for posting in first_postings
        }
        seen_page_signatures = {
            tuple(posting_identity(posting) for posting in first_postings)
        }
        offset = len(
            first_postings
        )

        while True:
            try:
                data, stats = self._run_page_request(
                    url=url,
                    headers=headers,
                    offset=offset,
                    company=company,
                    deadline=deadline,
                )
            except Exception as exc:
                stats = getattr(exc, "_workday_stats", None)
                if stats is not None:
                    report.http_attempts += stats.attempts
                    report.http_retries += stats.retries
                raise
            report.http_attempts += stats.attempts
            report.http_retries += stats.retries

            postings = (
                data.get(
                    "jobPostings"
                )
                or []
            )

            if not postings:
                break

            page_ids = tuple(
                posting_identity(posting)
                for posting in postings
            )
            has_new_postings = any(
                posting_id not in seen_posting_ids
                for posting_id in page_ids
            )
            if not has_new_postings:
                category = (
                    "repeated_page"
                    if page_ids in seen_page_signatures
                    else "no_new_postings"
                )
                raise ValueError(
                    "Workday listing incomplete "
                    f"category={category} "
                    f"company={company.id} "
                    f"board={headers['Referer'].rsplit('/', 1)[-1]} "
                    f"offset={offset}"
                )

            next_offset = offset + len(postings)
            if next_offset <= offset:
                raise ValueError(
                    "Workday listing incomplete category=no_forward_progress "
                    f"company={company.id} "
                    f"board={headers['Referer'].rsplit('/', 1)[-1]} "
                    f"offset={offset}"
                )

            all_postings.extend(
                postings
            )

            seen_posting_ids.update(page_ids)
            seen_page_signatures.add(page_ids)
            offset = next_offset

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

            if isinstance(data.get("jobPostings"), list):
                return True

        return False
