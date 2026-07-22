import re

from models import DetectionResult, PageSnapshot
from models.company import ProviderType

from .base import ProviderDetector


# Ashby serves boards from jobs.ashbyhq.com and the posting API from
# api.ashbyhq.com. Org slugs are case-sensitive (often the company name),
# so unlike Greenhouse/Lever we preserve the original casing.
_SLUG_PATTERNS = (
    re.compile(r"api\.ashbyhq\.com/posting-api/job-board/([A-Za-z0-9][A-Za-z0-9-]*)"),
    re.compile(r"jobs\.ashbyhq\.com/([A-Za-z0-9][A-Za-z0-9-]*)"),
)


class AshbyDetector(ProviderDetector):
    """Detects Ashby-hosted career pages and extracts the org slug."""

    def detect(self, snapshot: PageSnapshot) -> DetectionResult | None:
        haystack = f"{snapshot.final_url}\n{snapshot.html}"

        for pattern in _SLUG_PATTERNS:
            match = pattern.search(haystack)
            if match:
                slug = match.group(1)
                return DetectionResult(
                    provider=ProviderType.ASHBY,
                    confidence=0.95,
                    reason=f"Found Ashby board reference for '{slug}'.",
                    identifier=slug,
                )

        return None
