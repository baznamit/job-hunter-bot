import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from models import Job

_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"

class RejectionReason(str, Enum):
    INCLUDE_KEYWORD = "include_keyword"
    EXCLUDED_KEYWORD = "excluded_keyword"
    LOCATION = "location"
    SENIORITY = "seniority"


@dataclass
class FilterResult:
    included: bool
    reason: RejectionReason | None = None


@dataclass
class FilterDiagnostics:
    total: int = 0
    matched: int = 0
    include_keyword: int = 0
    excluded_keyword: int = 0
    location: int = 0
    seniority: int = 0

    samples: dict[RejectionReason, list[Job]] = field(
        default_factory=lambda: {
            RejectionReason.INCLUDE_KEYWORD: [],
            RejectionReason.EXCLUDED_KEYWORD: [],
            RejectionReason.LOCATION: [],
            RejectionReason.SENIORITY: [],
        }
    )

class JobFilter:
    
    _DIAGNOSTIC_ROLE_TERMS = (
        "software engineer",
        "software developer",
        "software development engineer",
        "backend engineer",
        "backend developer",
        "java engineer",
        "java developer",
        "application engineer",
        "application developer",
        "platform engineer",
        "product engineer",
        "api engineer",
        "cloud engineer",
        "distributed systems engineer",
        "member of technical staff",
        "mts",
        "sde",
        "computer scientist",
        "associate engineer",
        "associate software engineer",
        "engineer i",
        "engineer ii",
        "engineer iii",
    )

    _DIAGNOSTIC_IRRELEVANT_TERMS = (
        "marketing",
        "sales",
        "recruiter",
        "human resources",
        "designer",
        "data scientist",
        "data analyst",
        "machine learning",
        "android",
        "ios",
        "quality assurance",
        "qa engineer",
        "test engineer",
        "support engineer",
        "engineering manager",
        "vice president",
        "director",
        "data engineer",
        "ai engineer",
        "site reliability",
        "security engineer",
        "network engineer",
        "firmware",
    )

    def __init__(self) -> None:

        keyword_config = json.loads(
            (_CONFIG_DIR / "keywords.json").read_text(encoding="utf-8")
        )
        self.include_keywords: list[str] = [
            kw.lower() for kw in keyword_config["include"]
        ]
        self.exclude_keywords: list[str] = [
            kw.lower() for kw in keyword_config["exclude"]
        ]

        settings = json.loads(
            (_CONFIG_DIR / "settings.json").read_text(encoding="utf-8")
        )
        self.allowed_locations: list[str] = [
            loc.lower() for loc in settings["allowed_locations"]
        ]
        self.excluded_levels: list[str] = [
            lvl.lower() for lvl in settings["excluded_levels"]
        ]

    def should_include(self, job: Job) -> bool:
        if not self._keyword_match(job.title):
            return False
        if not self._location_match(job.location):
            return False
        if not self._seniority_match(job.title):
            return False
        return True

    def evaluate(self, job: Job) -> FilterResult:
        """
        Evaluate a job using the production filter rules and return the
        first rejection reason.

        The order intentionally matches should_include().
        """

        if not self._include_keyword_match(job.title):
            return FilterResult(
                included=False,
                reason=RejectionReason.INCLUDE_KEYWORD,
            )

        if not self._exclude_keyword_match(job.title):
            return FilterResult(
                included=False,
                reason=RejectionReason.EXCLUDED_KEYWORD,
            )

        if not self._location_match(job.location):
            return FilterResult(
                included=False,
                reason=RejectionReason.LOCATION,
            )

        if not self._seniority_match(job.title):
            return FilterResult(
                included=False,
                reason=RejectionReason.SENIORITY,
            )

        return FilterResult(included=True)
    
    def _include_keyword_match(self, title: str) -> bool:
        title = title.lower()
        return any(
            kw in title
            for kw in self.include_keywords
        )

    def _exclude_keyword_match(self, title: str) -> bool:
        title = title.lower()
        return not any(
            kw in title
            for kw in self.exclude_keywords
        )

    def _keyword_match(self, title: str) -> bool:
        return (
            self._include_keyword_match(title)
            and self._exclude_keyword_match(title)
        )

    def _location_match(self, location: str) -> bool:
        loc = location.lower()
        # Component-aware matching: a city name must appear at a location
        # boundary (start, after ", ", or after " - ") to prevent
        # "Remote - Canada" from matching "Remote".
        return any(
            loc == allowed
            or loc.startswith(allowed + ",")
            or loc.startswith(allowed + " ")
            or (", " + allowed) in loc
            or (" - " + allowed) in loc
            for allowed in self.allowed_locations
        )

    def _seniority_match(self, title: str) -> bool:
        title = title.lower()
        return not any(level in title for level in self.excluded_levels)

    def is_useful_near_miss(
        self,
        job: Job,
        reason: RejectionReason,
    ) -> bool:
        """
        Decide whether a rejected job is useful enough to show in
        diagnostics.

        This does not affect production filtering.
        """

        title = job.title.lower()
        location = job.location.lower()

        if any(
            term in title
            for term in self._DIAGNOSTIC_IRRELEVANT_TERMS
        ):
            return False

        role_signal = any(
            term in title
            for term in self._DIAGNOSTIC_ROLE_TERMS
        )

        current_keyword_signal = self._include_keyword_match(
            job.title
        )

        target_city = any(
            city in location
            for city in (
                "mumbai",
                "bangalore",
                "bengaluru",
            )
        )

        broad_location = (
        location == "india"
        or location.endswith(", india")
        or (
                "remote" in location
                and (
                    "india" in location
                    or location.strip() == "remote"
                )
            )
        )

        if reason == RejectionReason.INCLUDE_KEYWORD:
            # Ambiguous engineering titles in a target city are the most
            # valuable candidates for later description enrichment.
            engineering_signal = (
                "engineer" in title
                or "developer" in title
                or "computer scientist" in title
                or "technical staff" in title
            )

            return engineering_signal and (
                target_city or broad_location
            )

        if reason == RejectionReason.EXCLUDED_KEYWORD:
            return (
                role_signal
                and (target_city or broad_location)
            )

        if reason == RejectionReason.LOCATION:
            return (
                role_signal
                or current_keyword_signal
            ) and broad_location

        if reason == RejectionReason.SENIORITY:
            return (
                role_signal
                or current_keyword_signal
            ) and target_city

        return False

    def diagnose(
        self,
        jobs: list[Job],
        sample_limit: int = 5,
    ) -> FilterDiagnostics:
        diagnostics = FilterDiagnostics(
            total=len(jobs),
        )

        for job in jobs:
            result = self.evaluate(job)

            if result.included:
                diagnostics.matched += 1
                continue

            if result.reason is None:
                continue

            if result.reason == RejectionReason.INCLUDE_KEYWORD:
                diagnostics.include_keyword += 1

            elif result.reason == RejectionReason.EXCLUDED_KEYWORD:
                diagnostics.excluded_keyword += 1

            elif result.reason == RejectionReason.LOCATION:
                diagnostics.location += 1

            elif result.reason == RejectionReason.SENIORITY:
                diagnostics.seniority += 1

            samples = diagnostics.samples[result.reason]

            if (
                len(samples) < sample_limit
                and self.is_useful_near_miss(
                    job,
                    result.reason,
                )
            ):
                samples.append(job)

        return diagnostics
