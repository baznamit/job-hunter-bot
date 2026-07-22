"""
src.store
---------
Persistent "seen jobs" store backed by data/seen.json.

Keyed by Job URL (unique across all companies and ATS providers). On every
bot run, only jobs NOT in the store are notified; then all notified jobs are
marked seen so they are never re-sent.

The file is committed back to the repo after each run (see the scheduled
workflow) so state survives across stateless GitHub Actions runs.
"""

import json
from pathlib import Path

from models import Job


class SeenStore:

    def __init__(self, path: Path) -> None:
        self._path = path
        self._seen: set[str] = self._load()

    # ── Public API ────────────────────────────────────────────────────────────

    def filter_new(self, jobs: list[Job]) -> list[Job]:
        """Return only jobs that have not been seen before."""
        return [job for job in jobs if self._is_new(job)]

    def mark_seen(self, jobs: list[Job]) -> None:
        """Record jobs as seen and persist to disk immediately."""
        for job in jobs:
            self._seen.add(self._key(job))
        self._persist()

    @property
    def count(self) -> int:
        return len(self._seen)

    # ── Internals ─────────────────────────────────────────────────────────────

    def _is_new(self, job: Job) -> bool:
        return self._key(job) not in self._seen

    @staticmethod
    def _key(job: Job) -> str:
        # Use the canonical URL string as the global unique key.
        return str(job.url)

    def _load(self) -> set[str]:
        if not self._path.exists():
            return set()
        data = json.loads(self._path.read_text(encoding="utf-8"))
        return set(data.get("seen", []))

    def _persist(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"seen": sorted(self._seen)}, indent=2) + "\n"
        self._path.write_text(payload, encoding="utf-8")
