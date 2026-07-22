import json
from pathlib import Path

from models import Job

_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


class JobFilter:

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

    def _keyword_match(self, title: str) -> bool:
        title = title.lower()
        if not any(kw in title for kw in self.include_keywords):
            return False
        return not any(kw in title for kw in self.exclude_keywords)

    def _location_match(self, location: str) -> bool:
        location = location.lower()
        return any(allowed in location for allowed in self.allowed_locations)

    def _seniority_match(self, title: str) -> bool:
        title = title.lower()
        return not any(level in title for level in self.excluded_levels)
