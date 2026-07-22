from abc import ABC, abstractmethod

from models import DetectionResult, PageSnapshot


class ProviderDetector(ABC):
    """
    Base class for ATS provider detectors.

    A detector inspects an already-fetched page and decides whether the
    company's career site is powered by a specific ATS. Detectors never
    perform network I/O themselves, which keeps them pure and testable.
    """

    @abstractmethod
    def detect(self, snapshot: PageSnapshot) -> DetectionResult | None:
        """
        Return a DetectionResult if this detector recognises the ATS,
        otherwise None so the next detector can be tried.
        """
        raise NotImplementedError
