from models import DetectionResult, PageSnapshot
from models.company import ProviderType

from .ashby import AshbyDetector
from .base import ProviderDetector
from .greenhouse import GreenhouseDetector
from .lever import LeverDetector


# Ordered by detection confidence / specificity. New ATS detectors are added
# here as they are implemented (SmartRecruiters, Workday).
_DETECTORS: tuple[ProviderDetector, ...] = (
    GreenhouseDetector(),
    LeverDetector(),
    AshbyDetector(),
)


def detect_provider(snapshot: PageSnapshot) -> DetectionResult:
    """
    Run every registered detector against a fetched page and return the first
    match. Falls back to an UNKNOWN result when no ATS signature is found.
    """
    for detector in _DETECTORS:
        result = detector.detect(snapshot)
        if result is not None:
            return result

    return DetectionResult(
        provider=ProviderType.UNKNOWN,
        confidence=0.0,
        reason="No known ATS signature found on the page.",
    )
