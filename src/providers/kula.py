from __future__ import annotations

import html
import json
import re
from datetime import datetime

import requests

from models import Job
from models.company import Company

from .base import ProviderAdapter


_TIMEOUT = 30

_HEADERS = {
    "Accept": (
        "text/html,"
        "application/xhtml+xml,"
        "application/json;q=0.9,"
        "*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "User-Agent": (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/127.0.0.0 Safari/537.36"
    ),
}


class KulaAdapter(ProviderAdapter):
    """
    Adapter for public Kula career boards.

    Kula's public board pages are server-rendered and contain
    structured job objects in the HTML. Using that public
    representation avoids depending on Kula's authenticated
    or internal APIs.

    Example board:
        https://careers.kula.ai/clevertap
    """

    provider_name = "Kula"

    def _board_url(
        self,
        company: Company,
    ) -> str:
        base_url = (
            company.provider.config.base_url
        )

        if not base_url:
            raise ValueError(
                f"{company.name}: "
                "Kula provider requires base_url"
            )

        return base_url.rstrip("/")

    def _fetch_raw(
        self,
        company: Company,
    ) -> dict:
        url = self._board_url(
            company
        )

        response = requests.get(
            url,
            headers=_HEADERS,
            timeout=_TIMEOUT,
            allow_redirects=True,
        )

        self._check_response(
            response,
            company,
        )

        text = response.text

        jobs = self._extract_jobs(
            text
        )

        if not jobs:
            raise RuntimeError(
                f"{company.name}: "
                "Kula board returned no "
                "structured jobs"
            )

        return {
            "board_url": str(
                response.url
            ).rstrip("/"),
            "jobs": jobs,
        }

    @staticmethod
    def _json_string(
        value: str,
    ) -> str:
        """
        Decode a JSON string value captured from HTML.

        Kula's server-rendered state may contain escaped
        JSON strings.
        """

        try:
            return json.loads(
                f'"{value}"'
            )
        except (
            ValueError,
            TypeError,
        ):
            return html.unescape(
                value
            )

    @classmethod
    def _extract_jobs(
        cls,
        text: str,
    ) -> list[dict]:
        """
        Extract structured Kula job objects from the
        server-rendered board.

        We deliberately anchor extraction around numeric job
        IDs and the known public job fields rather than
        depending on a private frontend API.
        """

        decoded = html.unescape(
            text
        )

        # Kula/Next-style HTML can encode quotation marks in
        # script/state content.
        decoded = (
            decoded
            .replace('\\"', '"')
        )

        job_ids = set(
            re.findall(
                r'"id"\s*:\s*'
                r'(?:"(\d+)"|(\d+))',
                decoded,
                flags=re.IGNORECASE,
            )
        )

        numeric_ids = {
            first or second
            for first, second in job_ids
            if first or second
        }

        jobs: list[dict] = []

        for job_id in numeric_ids:
            # Find occurrences of this object and inspect a
            # bounded region. The board state may contain the
            # same job more than once.
            pattern = re.compile(
                r'"id"\s*:\s*'
                r'(?:"?'
                + re.escape(job_id)
                + r'"?)'
            )

            for match in pattern.finditer(
                decoded
            ):
                start = max(
                    0,
                    match.start() - 500,
                )

                end = min(
                    len(decoded),
                    match.start() + 12_000,
                )

                chunk = decoded[
                    start:end
                ]

                title = cls._field(
                    chunk,
                    "title",
                )

                location = cls._field(
                    chunk,
                    "location",
                )

                # These two fields distinguish an actual Kula
                # job record from unrelated objects that also
                # happen to have a numeric "id".
                if not (
                    title
                    and location
                ):
                    continue

                jobs.append(
                    {
                        "id": job_id,
                        "title": title,
                        "location": location,
                        "department": cls._field(
                            chunk,
                            "department",
                        ),
                        "employment_type":
                            cls._field(
                                chunk,
                                "employment_type",
                            ),
                        "launch_at": cls._field(
                            chunk,
                            "launch_at",
                        ),
                        "remote": cls._bool_field(
                            chunk,
                            "remote",
                        ),
                        "workplace": cls._field(
                            chunk,
                            "workplace",
                        ),
                        "city": cls._field(
                            chunk,
                            "city",
                        ),
                        "country_code":
                            cls._field(
                                chunk,
                                "country_code",
                            ),
                    }
                )

                break

        # Stable deterministic ordering is useful for tests,
        # diagnostics, and state comparison.
        jobs.sort(
            key=lambda item: str(
                item["id"]
            )
        )

        return jobs

    @classmethod
    def _field(
        cls,
        text: str,
        name: str,
    ) -> str | None:
        match = re.search(
            rf'"{re.escape(name)}"'
            r'\s*:\s*"'
            r'((?:\\.|[^"\\])*)"',
            text,
            flags=re.IGNORECASE,
        )

        if not match:
            return None

        value = cls._json_string(
            match.group(1)
        ).strip()

        return value or None

    @staticmethod
    def _bool_field(
        text: str,
        name: str,
    ) -> bool:
        match = re.search(
            rf'"{re.escape(name)}"'
            r'\s*:\s*(true|false)',
            text,
            flags=re.IGNORECASE,
        )

        if not match:
            return False

        return (
            match.group(1).lower()
            == "true"
        )

    @staticmethod
    def _posted_at(
        value: object,
    ) -> datetime | None:
        if not value:
            return None

        try:
            return datetime.fromisoformat(
                str(value).replace(
                    "Z",
                    "+00:00",
                )
            )
        except ValueError:
            return None

    def parse(
        self,
        raw: dict | list,
        company: Company,
    ) -> list[Job]:
        if not isinstance(
            raw,
            dict,
        ):
            return []

        board_url = str(
            raw.get("board_url")
            or self._board_url(company)
        ).rstrip("/")

        items = raw.get(
            "jobs"
        )

        if not isinstance(
            items,
            list,
        ):
            return []

        jobs: list[Job] = []
        seen_ids: set[str] = set()

        for item in items:
            if not isinstance(
                item,
                dict,
            ):
                continue

            job_id = str(
                item.get("id")
                or ""
            ).strip()

            title = str(
                item.get("title")
                or ""
            ).strip()

            location = str(
                item.get("location")
                or ""
            ).strip()

            if not (
                job_id
                and title
            ):
                continue

            if job_id in seen_ids:
                continue

            seen_ids.add(
                job_id
            )

            remote = bool(
                item.get("remote")
            )

            workplace = str(
                item.get("workplace")
                or ""
            ).strip().lower()

            if workplace == "remote":
                remote = True

            jobs.append(
                Job(
                    id=job_id,
                    title=title,
                    company=company.name,
                    location=(
                        location
                        or "Unknown"
                    ),
                    url=(
                        f"{board_url}/"
                        f"{job_id}/"
                    ),
                    posted_at=self._posted_at(
                        item.get(
                            "launch_at"
                        )
                    ),
                    department=(
                        item.get(
                            "department"
                        )
                        or None
                    ),
                    employment_type=(
                        item.get(
                            "employment_type"
                        )
                        or None
                    ),
                    remote=remote,
                )
            )

        return jobs

    def validate(
        self,
        company: Company,
    ) -> bool:
        raw = self._fetch_raw(
            company
        )

        jobs = raw.get(
            "jobs"
        )

        return bool(
            isinstance(
                jobs,
                list,
            )
            and jobs
        )
