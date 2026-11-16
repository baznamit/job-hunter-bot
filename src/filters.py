import re
import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from models import Job

_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"

_FOREIGN_COUNTRY_TERMS = (
    "united states",
    "usa",
    "us",
    "canada",
    "brazil",
    "united kingdom",
    "uk",
    "australia",
    "germany",
    "france",
    "ireland",
    "netherlands",
    "singapore",
    "japan",
    "china",
    "spain",
    "italy",
    "switzerland",
    "sweden",
    "poland",
    "mexico",
    "argentina",
    "colombia",
    "philippines",
    "malaysia",
    "indonesia",
    "thailand",
    "israel",
    "south africa",
    "new zealand",
    "united arab emirates",
    "uae",
)


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
        "platform automation engineer",
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
        location_settings = settings.get(
            "locations",
            {},
        )

        self.allowed_locations: list[str] = [
            location.lower()
            for location in location_settings.get(
                "allowed",
                [],
            )
        ]

        self.allow_india = bool(
            location_settings.get(
                "allow_india",
                True,
            )
        )

        self.allow_remote_india = bool(
            location_settings.get(
                "allow_remote_india",
                True,
            )
        )

        self.allow_plain_remote = bool(
            location_settings.get(
                "allow_plain_remote",
                True,
            )
        )

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
    
    @staticmethod
    def _normalize_role_text(value: str) -> str:
        """Normalize equivalent separators in role titles."""
        return re.sub(
            r"\s+",
            " ",
            re.sub(r"[-‐‑–—_/]+", " ", value.casefold()),
        ).strip()

    def _include_keyword_match(self, title: str) -> bool:
        normalized_title = self._normalize_role_text(title)

        return any(
            self._normalize_role_text(keyword)
            in normalized_title
            for keyword in self.include_keywords
        )

    def _exclude_keyword_match(self, title: str) -> bool:
        """
        Reject excluded words/phrases without accidental substring matches.

        Examples:
            "Software Engineer Intern"   -> rejected by "intern"
            "Software Engineer Internal" -> NOT rejected by "intern"
            "ML Engineer"                -> rejected by "ml"
        """

        title = title.lower()

        return not any(
            re.search(
                rf"(?<!\w){re.escape(keyword)}(?!\w)",
                title,
            )
            for keyword in self.exclude_keywords
        )

    def _keyword_match(self, title: str) -> bool:
        return (
            self._include_keyword_match(title)
            and self._exclude_keyword_match(title)
        )

    @staticmethod
    def _location_segments(location: str) -> list[str]:
        return [
            segment.strip().casefold()
            for segment in re.split(r"\s*\|\s*|\s+/\s+", location)
            if segment.strip()
        ]

    @staticmethod
    def _contains_location_term(location: str, term: str) -> bool:
        return bool(
            re.search(
                rf"(?<![\w-]){re.escape(term)}(?![\w-])",
                location,
            )
        )

    @classmethod
    def _has_foreign_country(cls, location: str) -> bool:
        return any(
            cls._contains_location_term(location, country)
            for country in _FOREIGN_COUNTRY_TERMS
        )

    def _location_has_allowed_city(self, location: str) -> bool:
        return any(
            not self._has_foreign_country(segment)
            and any(
                self._contains_location_term(segment, city)
                for city in self.allowed_locations
            )
            for segment in self._location_segments(location)
        )

    def _location_is_remote_india(self, location: str) -> bool:
        return any(
            self._contains_location_term(segment, "remote")
            and self._contains_location_term(segment, "india")
            and not self._has_foreign_country(segment)
            for segment in self._location_segments(location)
        )

    def _location_is_plain_remote(self, location: str) -> bool:
        return any(
            segment == "remote"
            for segment in self._location_segments(location)
        )

    def _location_is_india_wide(self, location: str) -> bool:
        return any(
            segment == "india"
            for segment in self._location_segments(location)
        )

    def _location_is_broad_target(self, location: str) -> bool:
        for segment in self._location_segments(location):
            if self._has_foreign_country(segment):
                continue
            if (
                self.allow_india
                and (
                    segment == "india"
                    or segment.endswith(", india")
                )
            ):
                return True
            if (
                self.allow_remote_india
                and self._contains_location_term(segment, "remote")
                and self._contains_location_term(segment, "india")
            ):
                return True
            if (
                self.allow_plain_remote
                and segment == "remote"
            ):
                return True
        return False

    def _location_is_diagnostic_target(self, location: str) -> bool:
        return (
            self._location_has_allowed_city(location)
            or self._location_is_broad_target(location)
        )

    def _location_priority(self, location: str) -> int:
        if self._location_has_allowed_city(location):
            return 40
        if (
            self.allow_remote_india
            and self._location_is_remote_india(location)
        ):
            return 25
        if (
            self.allow_plain_remote
            and self._location_is_plain_remote(location)
        ):
            return 15
        if self.allow_india and self._location_is_india_wide(location):
            return 10
        return 0

    def _location_match(self, location: str) -> bool:
        """
        Accept:
        - Mumbai / Bangalore / Bengaluru variants
        - India-wide jobs
        - Remote India
        - plain Remote

        Reject remote jobs explicitly tied to another country.
        """

        if self._location_has_allowed_city(location):
            return True
        if self.allow_india and self._location_is_india_wide(location):
            return True
        if self.allow_remote_india and self._location_is_remote_india(location):
            return True
        return (
            self.allow_plain_remote
            and self._location_is_plain_remote(location)
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

        target_city = self._location_has_allowed_city(location)
        broad_location = self._location_is_broad_target(location)

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
