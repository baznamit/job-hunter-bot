import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock


class RecoveryStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = Lock()
        self._data = self._load()

    def _load(self) -> dict:
        if not self._path.exists():
            return {}

        try:
            data = json.loads(
                self._path.read_text(
                    encoding="utf-8"
                )
            )
        except (
            json.JSONDecodeError,
            OSError,
        ):
            return {}

        if not isinstance(data, dict):
            return {}

        return data

    def should_attempt(
        self,
        company_id: str,
    ) -> tuple[bool, datetime | None]:
        entry = self._data.get(company_id)

        if not entry:
            return True, None

        retry_after = entry.get(
            "retry_after"
        )

        if not retry_after:
            return True, None

        try:
            retry_at = datetime.fromisoformat(
                retry_after
            )
        except ValueError:
            return True, None

        now = datetime.now(
            timezone.utc
        )

        return now >= retry_at, retry_at

    def record_failure(
        self,
        company_id: str,
        *,
        base_hours: int,
        max_hours: int,
    ) -> None:
        with self._lock:
            previous = self._data.get(
                company_id,
                {}
            )

            failures = int(
                previous.get(
                    "failures",
                    0,
                )
            ) + 1

            cooldown_hours = min(
                base_hours
                * (2 ** (failures - 1)),
                max_hours,
            )

            now = datetime.now(
                timezone.utc
            )

            self._data[company_id] = {
                "failures": failures,
                "last_failure": (
                    now.isoformat()
                ),
                "retry_after": (
                    now
                    + timedelta(
                        hours=cooldown_hours
                    )
                ).isoformat(),
            }

            self._persist()

    def clear(
        self,
        company_id: str,
    ) -> None:
        with self._lock:
            if company_id not in self._data:
                return

            del self._data[
                company_id
            ]

            self._persist()

    def _persist(self) -> None:
        self._path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        payload = (
            json.dumps(
                self._data,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )

        self._path.write_text(
            payload,
            encoding="utf-8",
        )
