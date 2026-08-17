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
    ) -> None:
        self.company = company
        self.provider = provider

        super().__init__(
            f"{provider} temporary failure for {company}: {message}"
        )