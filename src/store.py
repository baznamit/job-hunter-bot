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
import os
from pathlib import Path
import tempfile

from models import Job


class SeenStore:

    def __init__(self, path: Path) -> None:
        self._path = path
        self._seen: set[str] = self._load()

    # ── Public API ────────────────────────────────────────────────────────────

    def filter_new(self, jobs: list[Job]) -> list[Job]:
        """Return unseen jobs once each, preserving input order."""
        result = []
        candidates = set(self._seen)

        for job in jobs:
            key = self._key(job)
            if key in candidates:
                continue
            candidates.add(key)
            result.append(job)

        return result

    def mark_seen(self, jobs: list[Job]) -> None:
        """Record jobs as seen and persist to disk immediately."""
        updated = set(self._seen)
        for job in jobs:
            updated.add(self._key(job))
        self._persist(updated)
        self._seen = updated

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

    def _persist(self, seen: set[str] | None = None) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {"seen": sorted(self._seen if seen is None else seen)},
            indent=2,
        ) + "\n"
        temporary_path = None

        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self._path.parent,
                prefix=f".{self._path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                temporary.write(payload)
                temporary.flush()
                os.fsync(temporary.fileno())

            os.replace(temporary_path, self._path)
            temporary_path = None
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink()
                except FileNotFoundError:
                    pass
