import re

from models import DetectionResult, PageSnapshot
from models.company import ProviderType

from .base import ProviderDetector


# Greenhouse exposes boards under a handful of host patterns. Each pattern
# captures the board slug that we later store in Provider.config.board.
_SLUG_PATTERNS = (
    re.compile(r"boards-api\.greenhouse\.io/v1/boards/([a-z0-9_-]+)", re.IGNORECASE),
    re.compile(r"job-boards\.greenhouse\.io/([a-z0-9_-]+)", re.IGNORECASE),
    # Embed script (`/embed/job_board/js?for=`) and iframe (`/embed/job_board?for=`).
    re.compile(r"greenhouse\.io/embed/job_board[^\"'?]*\?for=([a-z0-9_-]+)", re.IGNORECASE),
    re.compile(r"boards\.greenhouse\.io/([a-z0-9_-]+)", re.IGNORECASE),
)

# Slugs that appear in the patterns above but are not real board names.
_RESERVED_SLUGS = {"embed", "v1", "boards"}


class GreenhouseDetector(ProviderDetector):
    """Detects Greenhouse-hosted career pages and extracts the board slug."""

    def detect(self, snapshot: PageSnapshot) -> DetectionResult | None:
        haystack = f"{snapshot.final_url}\n{snapshot.html}"

        slug = self._extract_slug(haystack)
        if slug is None:
            return None

        return DetectionResult(
            provider=ProviderType.GREENHOUSE,
            confidence=0.95,
            reason=f"Found Greenhouse board reference for '{slug}'.",
            identifier=slug,
        )

    def _extract_slug(self, haystack: str) -> str | None:
        for pattern in _SLUG_PATTERNS:
            match = pattern.search(haystack)
            if match:
                slug = match.group(1).lower()
                if slug not in _RESERVED_SLUGS:
                    return slug
        return None
