from email.utils import parsedate_to_datetime
import time


def parse_retry_after(value: str | None, now: float | None = None) -> float | None:
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


class ProviderError(Exception):
    """Base exception for ATS/provider failures."""


class ProviderNotFoundError(ProviderError):
    """
    Raised when a configured ATS endpoint returns HTTP 404.

    A 404 usually means that the stored provider configuration is stale:
    wrong board, tenant, organization, cluster, or ATS provider.
    """

    def __init__(
        self,
        company: str,
        provider: str,
        url: str,
    ) -> None:
        self.company = company
        self.provider = provider
        self.url = url

        super().__init__(
            f"{provider} endpoint not found for {company}: {url}"
        )


class ProviderTemporaryError(ProviderError):
    """
    Raised for temporary ATS failures that should be retried later.

    Examples:
    - HTTP 429
    - HTTP 5xx
    """

    def __init__(
        self,
        company: str,
        provider: str,
        message: str,
        *,
        status: int | None = None,
        category: str | None = None,
        retry_after: str | None = None,
        retry_after_seconds: float | None = None,
        endpoint: str | None = None,
        operation: str | None = None,
    ) -> None:
        self.company = company
        self.provider = provider
        self.status = status
        self.status_code = status
        self.http_status = status
        self.category = category
        self.retry_after = retry_after
        self.retry_after_seconds = (
            retry_after_seconds
            if retry_after_seconds is not None
            else parse_retry_after(retry_after)
        )
        self.endpoint = endpoint
        self.operation = operation

        super().__init__(
            f"{provider} temporary failure for {company}: {message}"
        )
