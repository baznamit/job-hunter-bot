import re
from urllib.parse import unquote

from models import DetectionResult, PageSnapshot
from models.company import ProviderType

from .base import ProviderDetector


_WORKDAY_URL_PATTERN = re.compile(
    r"https?://"
    r"(?P<tenant>[a-z0-9-]+)\."
    r"(?P<cluster>wd[0-9]+)\."
    r"myworkdayjobs\.com"
    r"(?:/[a-z]{2}-[A-Z]{2})?"
    r"/(?P<board>[a-zA-Z0-9_-]+)",
    re.IGNORECASE,
)

# Workday paths that are infrastructure/API paths rather than
# public career-site board names.
_RESERVED_BOARDS = {
    "wday",
    "job",
    "jobs",
}


class WorkdayDetector(ProviderDetector):
    """
    Detect a public Workday career-site URL.

    Example:

        https://visa.wd5.myworkdayjobs.com/en-US/Visa

    becomes:

        tenant  = visa
        cluster = wd5
        board   = Visa
    """

    def detect(
        self,
        snapshot: PageSnapshot,
    ) -> DetectionResult | None:
        haystack = (
            f"{snapshot.final_url}\n"
            f"{unquote(snapshot.html)}"
        )

        match = _WORKDAY_URL_PATTERN.search(haystack)

        if match is None:
            return None

        tenant = match.group("tenant").lower()
        cluster = match.group("cluster").lower()
        board = match.group("board")

        if board.lower() in _RESERVED_BOARDS:
            return None

        return DetectionResult(
            provider=ProviderType.WORKDAY,
            confidence=0.95,
            reason=(
                "Found Workday career-site reference "
                f"for tenant '{tenant}', board '{board}', "
                f"cluster '{cluster}'."
            ),
            identifier=board,
            config={
                "tenant": tenant,
                "cluster": cluster,
                "board": board,
            },
        )