import json
from urllib.parse import urlencode

import requests

from models import Job
from models.company import Company

from .base import ProviderAdapter


_TIMEOUT = 30
_DEFAULT_PAGE_SIZE = 25
_MAX_PAGE_SIZE = 100
_MAX_PAGES = 100


class RippleHireAdapter(ProviderAdapter):
    """Fetch public career-site jobs from RippleHire's candidate API."""

    provider_name = "RippleHire"

    def _configuration(self, company: Company) -> tuple[str, str, str, int, int]:
        config = company.provider.config
        if not config.base_url:
            raise ValueError(
                f"{company.name}: RippleHire provider requires base_url"
            )
        if not config.token:
            raise ValueError(
                f"{company.name}: RippleHire provider requires token"
            )
        if not config.source:
            raise ValueError(
                f"{company.name}: RippleHire provider requires source"
            )

        page_size = config.page_size or _DEFAULT_PAGE_SIZE
        if not 1 <= page_size <= _MAX_PAGE_SIZE:
            raise ValueError(
                f"{company.name}: RippleHire page_size must be between 1 and "
                f"{_MAX_PAGE_SIZE}"
            )

        max_pages = min(config.max_pages or _MAX_PAGES, _MAX_PAGES)
        base_url = config.base_url.rstrip("/") + "/"
        return base_url, config.token, config.source, page_size, max_pages

    def _request_page(
        self,
        session: requests.Session,
        company: Company,
        base_url: str,
        token: str,
        source: str,
        page: int,
        page_size: int,
    ) -> dict:
        url = f"{base_url}candidatejobsearch"
        params = {
            "token": token,
            "source": source,
            "page": page,
            "search": "*:*",
            "pagesize": page_size,
        }
        response = session.post(
            url,
            data={
                "careerSiteUrlParams": json.dumps(
                    params,
                    separators=(",", ":"),
                ),
                "lang": "en",
            },
            headers={"Accept": "application/json"},
            timeout=_TIMEOUT,
        )
        self._check_response(response, company)

        try:
            payload = response.json()
        except requests.exceptions.JSONDecodeError as exc:
            raise ValueError(
                f"{company.name}: RippleHire returned invalid JSON"
            ) from exc

        if not isinstance(payload, dict):
            raise ValueError(
                f"{company.name}: RippleHire response must be an object"
            )
        return payload

    def _fetch_raw(self, company: Company) -> dict:
        base_url, token, source, page_size, max_pages = self._configuration(
            company
        )
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (compatible; JobHunterBot/1.0)"
                ),
                "Referer": (
                    f"{base_url}?"
                    f"{urlencode({'token': token, 'source': source})}"
                ),
                "X-Requested-With": "XMLHttpRequest",
            }
        )

        # The public candidate site initializes a session before its listing call.
        landing = session.get(
            f"{base_url}?{urlencode({'token': token, 'source': source})}",
            timeout=_TIMEOUT,
        )
        self._check_response(landing, company)

        first_page = self._request_page(
            session,
            company,
            base_url,
            token,
            source,
            page=0,
            page_size=page_size,
        )
        total = first_page.get("totalJobCount")
        if (
            not isinstance(total, int)
            or isinstance(total, bool)
            or total < 0
        ):
            raise ValueError(
                f"{company.name}: RippleHire response has invalid totalJobCount"
            )

        page_count = max(1, (total + page_size - 1) // page_size)
        if page_count > max_pages:
            raise ValueError(
                f"{company.name}: RippleHire inventory exceeds max_pages"
            )

        records: list[dict] = []
        seen_ids: set[str] = set()
        for page_number in range(page_count):
            payload = (
                first_page
                if page_number == 0
                else self._request_page(
                    session,
                    company,
                    base_url,
                    token,
                    source,
                    page=page_number,
                    page_size=page_size,
                )
            )

            if payload.get("totalJobCount") != total:
                raise ValueError(
                    f"{company.name}: RippleHire total changed during pagination"
                )

            page_records = payload.get("jobVoList")
            if not isinstance(page_records, list):
                raise ValueError(
                    f"{company.name}: RippleHire response is missing jobVoList"
                )

            expected = min(page_size, total - page_number * page_size)
            if len(page_records) != expected:
                raise ValueError(
                    f"{company.name}: RippleHire returned an incomplete page"
                )

            for record in page_records:
                if not isinstance(record, dict):
                    raise ValueError(
                        f"{company.name}: RippleHire returned an invalid job"
                    )
                job_id = str(record.get("jobSeq") or record.get("jobId") or "")
                title = str(record.get("jobTitle") or "").strip()
                if not job_id or not title or job_id in seen_ids:
                    raise ValueError(
                        f"{company.name}: RippleHire job records are incomplete "
                        "or repeated"
                    )
                seen_ids.add(job_id)
                records.append(record)

        if len(records) != total:
            raise ValueError(
                f"{company.name}: RippleHire inventory count does not match total"
            )

        return {"jobVoList": records, "totalJobCount": total}

    def parse(self, raw: dict | list, company: Company) -> list[Job]:
        if not isinstance(raw, dict):
            raise ValueError(
                f"{company.name}: expected RippleHire object response"
            )
        records = raw.get("jobVoList")
        if not isinstance(records, list):
            raise ValueError(
                f"{company.name}: RippleHire response is missing jobVoList"
            )

        config = company.provider.config
        query = urlencode(
            {"token": config.token, "source": config.source}
        )
        detail_base = f"{config.base_url.rstrip('/')}/?{query}#detail/job/"
        jobs: list[Job] = []

        for record in records:
            if not isinstance(record, dict):
                continue

            job_id = str(record.get("jobSeq") or record.get("jobId") or "").strip()
            title = str(record.get("jobTitle") or "").strip()
            if not job_id or not title:
                continue

            location_value = (
                record.get("locations")
                or record.get("jobLocation")
                or record.get("jobLocationList")
                or "Unknown"
            )
            if isinstance(location_value, list):
                location = ", ".join(
                    str(value).strip()
                    for value in location_value
                    if str(value).strip()
                ) or "Unknown"
            else:
                location = str(location_value).strip() or "Unknown"

            jobs.append(
                Job(
                    id=job_id,
                    title=title,
                    company=company.name,
                    location=location,
                    url=f"{detail_base}{job_id}",
                )
            )

        return jobs
