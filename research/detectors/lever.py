import re

from models import DetectionResult, PageSnapshot
from models.company import ProviderType

from .base import ProviderDetector


# Lever hosts boards on jobs.lever.co and serves postings from api.lever.co.
# Both expose the company slug we store in Provider.config.
_SLUG_PATTERNS = (
    re.compile(r"api\.lever\.co/v0/postings/([a-z0-9][a-z0-9-]*)", re.IGNORECASE),
    re.compile(r"jobs\.lever\.co/([a-z0-9][a-z0-9-]*)", re.IGNORECASE),
)


class LeverDetector(ProviderDetector):
    """Detects Lever-hosted career pages and extracts the company slug."""

    def detect(self, snapshot: PageSnapshot) -> DetectionResult | None:
        haystack = f"{snapshot.final_url}\n{snapshot.html}"

        for pattern in _SLUG_PATTERNS:
            match = pattern.search(haystack)
            if match:
                slug = match.group(1).lower()
                return DetectionResult(
                    provider=ProviderType.LEVER,
                    confidence=0.95,
                    reason=f"Found Lever board reference for '{slug}'.",
                    identifier=slug,
                )

        return None
