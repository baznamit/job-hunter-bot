from abc import ABC, abstractmethod

import requests

from models import Job
from models.company import Company

from .exceptions import ProviderNotFoundError, ProviderTemporaryError


class ProviderAdapter(ABC):
    """
    Base class for ATS provider adapters.

    Subclasses implement:
    - `_fetch_raw()` for provider-specific API calls
    - `parse()` for converting provider responses into Job objects

    Common HTTP failure classification is handled here.
    """

    provider_name = "ATS"

    def fetch_jobs(self, company: Company) -> list[Job]:
        raw = self._fetch_raw(company)
        return self.parse(raw, company)

    def validate(self, company: Company) -> bool:
        """
        Validate that this provider configuration is reachable.

        Providers may override this with a cheaper request when normal
        fetching is expensive.
        """
        self._fetch_raw(company)
        return True

    def _check_response(
    self,
    response: requests.Response,
    company: Company,
    ) -> None:
        """
        Classify provider HTTP failures.

        404 / 422:
            The configured ATS mapping is probably stale.

            Workday may return 422 when the tenant exists but the
            configured career-site board is invalid or stale.

        429 / 5xx:
            Temporary provider failure. This must NOT trigger ATS
            rediscovery.

        Other 4xx:
            Let requests raise its standard HTTPError.
        """

        if response.status_code in (404, 422):
            raise ProviderNotFoundError(
                company=company.name,
                provider=self.provider_name,
                url=response.url,
            )

        if response.status_code == 429 or response.status_code >= 500:
            raise ProviderTemporaryError(
                company=company.name,
                provider=self.provider_name,
                message=(
                    f"HTTP {response.status_code} "
                    f"from {response.url}"
                ),
            )

        response.raise_for_status()

    @abstractmethod
    def _fetch_raw(self, company: Company) -> dict | list:
        raise NotImplementedError

    @abstractmethod
    def parse(
        self,
        raw: dict | list,
        company: Company,
    ) -> list[Job]:
        raise NotImplementedError