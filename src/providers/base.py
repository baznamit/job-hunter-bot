from abc import ABC, abstractmethod

from models import Job
from models.company import Company


class ProviderAdapter(ABC):
    """
    Base class for ATS provider adapters.

    Subclasses implement two methods:
    - `_fetch_raw`  — makes the HTTP call and returns raw API data.
    - `parse`       — converts raw API data into a list of Jobs (pure, no I/O).

    `fetch_jobs` wires them together. Tests call `parse` directly with fixture
    data so no network is needed during push CI.
    """

    def fetch_jobs(self, company: Company) -> list[Job]:
        raw = self._fetch_raw(company)
        return self.parse(raw, company)

    @abstractmethod
    def _fetch_raw(self, company: Company) -> dict | list:
        raise NotImplementedError

    @abstractmethod
    def parse(self, raw: dict | list, company: Company) -> list[Job]:
        raise NotImplementedError
