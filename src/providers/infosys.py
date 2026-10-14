from __future__ import annotations

from datetime import datetime
from urllib.parse import urlencode, urlparse

import requests

from models import Job
from models.company import Company

from .base import ProviderAdapter


_DEFAULT_CONFIG_URL = (
    "https://career.infosys.com/"
    "assets/environments/environment.json"
)

_CAREERS_URL = "https://career.infosys.com"
_JOB_ENDPOINT = "getCareerSearchJobs"
_DEFAULT_SOURCE_ID = "1,21"

_TIMEOUT = (10, 40)
_MAX_RESPONSE_BYTES = 25_000_000

_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Origin": _CAREERS_URL,
    "Referer": f"{_CAREERS_URL}/jobs",
}


class InfosysAdapter(ProviderAdapter):
    """
    Public Infosys careers adapter.

    The frontend publishes JobsUnAuthUrl in its runtime
    environment.json configuration.

    The anonymous getCareerSearchJobs endpoint returns
    a JSON array containing the current job inventory.
    """

    provider_name = "Infosys"

    @staticmethod
    def _config_url(company: Company) -> str:
        return (
            company.provider.config.config_url
            or _DEFAULT_CONFIG_URL
        )

    @staticmethod
    def _source_id(company: Company) -> str:
        return (
            company.provider.config.source_id
            or _DEFAULT_SOURCE_ID
        )

    @staticmethod
    def _posted_at(value: object) -> datetime | None:
        if not value:
            return None

        try:
            return datetime.fromisoformat(
                str(value).replace("Z", "+00:00")
            )
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _job_url(reference_code: str) -> str:
        return (
            f"{_CAREERS_URL}/jobdesc?"
            + urlencode({
                "jobReferenceCode": reference_code
            })
        )

    @staticmethod
    def _validate_api_base(value: object) -> str:
        base = str(value or "").strip()

        parsed = urlparse(base)

        if (
            parsed.scheme != "https"
            or parsed.hostname
            != "intapgateway.infosysapps.com"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "Infosys runtime configuration returned "
                "an unexpected JobsUnAuthUrl"
            )

        if not parsed.path.rstrip("/").endswith(
            "/careersci/search/intapjbsrch"
        ):
            raise ValueError(
                "Infosys JobsUnAuthUrl has an "
                "unexpected API path"
            )

        return base.rstrip("/") + "/"

    def _fetch_raw(self, company: Company) -> list:
        with requests.Session() as session:
            session.headers.update(_HEADERS)

            config_response = session.get(
                self._config_url(company),
                timeout=_TIMEOUT,
            )

            self._check_response(
                config_response,
                company,
            )

            content_type = (
                config_response.headers.get(
                    "Content-Type", ""
                ).lower()
            )

            if "json" not in content_type:
                raise RuntimeError(
                    f"{company.name}: Infosys runtime "
                    "configuration was not JSON"
                )

            config = config_response.json()

            if not isinstance(config, dict):
                raise RuntimeError(
                    f"{company.name}: invalid Infosys "
                    "runtime configuration"
                )

            api_base = self._validate_api_base(
                config.get("JobsUnAuthUrl")
            )

            endpoint = (
                api_base + _JOB_ENDPOINT
            )

            response = session.get(
                endpoint,
                params={
                    "sourceId": self._source_id(company),
                    "searchText": "ALL",
                },
                timeout=_TIMEOUT,
                stream=True,
            )

            try:
                self._check_response(
                    response,
                    company,
                )

                content_type = (
                    response.headers.get(
                        "Content-Type", ""
                    ).lower()
                )

                if "json" not in content_type:
                    raise RuntimeError(
                        f"{company.name}: Infosys jobs "
                        "endpoint returned non-JSON content"
                    )

                chunks = []
                total_bytes = 0

                for chunk in response.iter_content(
                    chunk_size=65536
                ):
                    if not chunk:
                        continue

                    total_bytes += len(chunk)

                    if total_bytes > _MAX_RESPONSE_BYTES:
                        raise RuntimeError(
                            f"{company.name}: Infosys "
                            "response exceeds size limit"
                        )

                    chunks.append(chunk)

                import json

                raw = json.loads(
                    b"".join(chunks)
                )

            finally:
                response.close()

        if not isinstance(raw, list):
            raise RuntimeError(
                f"{company.name}: expected Infosys "
                "jobs API to return a JSON array"
            )

        if not raw:
            raise RuntimeError(
                f"{company.name}: Infosys API returned "
                "an unexpectedly empty job inventory"
            )

        if not all(
            isinstance(item, dict)
            for item in raw
        ):
            raise RuntimeError(
                f"{company.name}: Infosys API contains "
                "non-object job records"
            )

        print(
            f"  [INFOSYS] {company.name}: "
            f"raw_jobs={len(raw)}"
        )

        return raw

    def parse(
        self,
        raw: dict | list,
        company: Company,
    ) -> list[Job]:
        if not isinstance(raw, list):
            raise ValueError(
                "Infosys parser expects a list"
            )

        jobs: list[Job] = []
        seen: set[str] = set()

        for item in raw:
            if not isinstance(item, dict):
                raise ValueError(
                    "Infosys job record is not an object"
                )

            reference_code = str(
                item.get("referenceCode") or ""
            ).strip()

            title = str(
                item.get("postingTitle") or ""
            ).strip()

            location = " ".join(
                str(
                    item.get("location") or ""
                ).split()
            )

            if not reference_code or not title:
                raise ValueError(
                    "Infosys job record missing "
                    "referenceCode or postingTitle"
                )

            if reference_code in seen:
                continue

            seen.add(reference_code)

            jobs.append(
                Job(
                    id=reference_code,
                    title=title,
                    company=company.name,
                    location=location or "Unknown",
                    url=self._job_url(
                        reference_code
                    ),
                    posted_at=self._posted_at(
                        item.get("createdOn")
                    ),
                    department=(
                        str(item.get("unit")).strip()
                        if item.get("unit")
                        else None
                    ),
                    remote=False,
                )
            )

        if not jobs:
            raise RuntimeError(
                f"{company.name}: Infosys parser "
                "produced no valid jobs"
            )

        print(
            f"  [INFOSYS] {company.name}: "
            f"normalized_jobs={len(jobs)}"
        )

        return jobs