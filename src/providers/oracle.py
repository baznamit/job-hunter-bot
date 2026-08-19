import sys
import uuid
from datetime import datetime

import requests

from models import Job
from models.company import (
    Company,
    OracleSiteConfig,
)

from .base import ProviderAdapter


_TIMEOUT = 30
_PAGE_SIZE = 200
_MAX_PAGES = 100


class OracleAdapter(ProviderAdapter):

    provider_name = "Oracle Recruiting Cloud"

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "User-Agent": "JobHunterBot/1.0",
            "ora-irc-language": "en",
            "ora-irc-cx-userid": str(uuid.uuid4()),
        }

    def _listing_url(
        self,
        company: Company,
    ) -> str:
        host = company.provider.config.host

        return (
            f"https://{host}/"
            "hcmRestApi/resources/latest/"
            "recruitingCEJobRequisitions"
        )

    def _fetch_site(
        self,
        company: Company,
        site: OracleSiteConfig,
    ) -> list[dict]:
        """
        Fetch every posting from one Oracle Candidate Experience site.

        Oracle CE pagination is controlled inside the findReqs finder,
        not by the generic REST limit/offset query parameters.
        """

        url = self._listing_url(company)

        all_jobs: list[dict] = []
        seen_ids: set[str] = set()

        offset = 0
        total: int | None = None

        for _ in range(_MAX_PAGES):
            finder = (
                "findReqs;"
                f"siteNumber={site.site_number},"
                f"limit={_PAGE_SIZE},"
                f"offset={offset}"
            )

            response = requests.get(
                url,
                params={
                    "onlyData": "true",
                    "expand": "requisitionList",
                    "finder": finder,
                },
                headers=self._headers(),
                timeout=_TIMEOUT,
            )

            self._check_response(
                response,
                company,
            )

            data = response.json()

            items = data.get("items") or []

            if not items:
                break

            root = items[0]

            postings = (
                root.get("requisitionList")
                or []
            )

            reported_total = root.get(
                "TotalJobsCount"
            )

            print(
                f"  [ORACLE] {company.name}: "
                f"site={site.site_number}, "
                f"offset={offset}, "
                f"returned={len(postings)}, "
                f"reported_total={reported_total}",
                file=sys.stderr,
            )

            page_ids = [
                str(posting["Id"])
                for posting in postings
                if posting.get("Id") is not None
            ]

            if page_ids:
                print(
                    f"  [ORACLE] {company.name}: "
                    f"page_ids={page_ids[0]}..{page_ids[-1]}",
                    file=sys.stderr,
                )

            if (
                isinstance(reported_total, int)
                and reported_total >= 0
            ):
                total = reported_total

            if not postings:
                break

            new_jobs: list[dict] = []

            for posting in postings:
                job_id = posting.get("Id")

                if job_id is None:
                    continue

                job_id = str(job_id)

                if job_id in seen_ids:
                    continue

                seen_ids.add(job_id)

                # Preserve the site that produced this job so parse()
                # can construct the correct browser-facing URL.
                new_jobs.append(
                    {
                        "job": posting,
                        "site_path": site.site_path,
                        "public_url_prefix":
                            site.public_url_prefix,
                    }
                )

            if not new_jobs:
                raise RuntimeError(
                    f"{company.name}: Oracle pagination "
                    f"stalled at offset {offset} "
                    f"for site {site.site_number}"
                )

            all_jobs.extend(new_jobs)

            if (
                total is not None
                and len(seen_ids) >= total
            ):
                break

            offset += len(postings)

        else:
            raise RuntimeError(
                f"{company.name}: Oracle pagination "
                f"exceeded {_MAX_PAGES} pages "
                f"for site {site.site_number}"
            )

        print(
            f"  [ORACLE] {company.name}: "
            f"site={site.site_number} complete — "
            f"{len(all_jobs)} unique postings collected",
            file=sys.stderr,
        )
        
        return all_jobs

    def _fetch_raw(
        self,
        company: Company,
    ) -> dict:
        config = company.provider.config

        all_jobs: list[dict] = []
        seen_ids: set[str] = set()

        for site in config.sites:
            if not site.enabled:
                continue

            site_jobs = self._fetch_site(
                company,
                site,
            )

            for wrapped in site_jobs:
                posting = wrapped["job"]
                job_id = str(posting["Id"])

                # A requisition may appear on more than one Candidate
                # Experience site. Keep only the first occurrence.
                if job_id in seen_ids:
                    continue

                seen_ids.add(job_id)
                all_jobs.append(wrapped)

        return {
            "requisitions": all_jobs,
        }

    def _build_public_url(
        self,
        company: Company,
        site_path: str,
        public_url_prefix: str | None,
        job_id: str,
    ) -> str:
        if public_url_prefix:
            return (
                f"{public_url_prefix.rstrip('/')}/"
                f"{job_id}"
            )

        host = company.provider.config.host

        return (
            f"https://{host}/"
            "hcmUI/CandidateExperience/en/sites/"
            f"{site_path}/job/{job_id}"
        )

    def _parse_date(
        self,
        value: str | None,
    ) -> datetime | None:
        if not value:
            return None

        try:
            return datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )
        except ValueError:
            return None

    def parse(
        self,
        raw: dict,
        company: Company,
    ) -> list[Job]:
        jobs: list[Job] = []

        for wrapped in raw.get(
            "requisitions",
            [],
        ):
            try:
                item = wrapped["job"]

                job_id = str(item["Id"])
                title = item["Title"]

                location = (
                    item.get("PrimaryLocation")
                    or "Unknown"
                )

                department = (
                    item.get("Department")
                    or item.get("JobFamily")
                    or item.get("JobFunction")
                )

                url = self._build_public_url(
                    company=company,
                    site_path=wrapped["site_path"],
                    public_url_prefix=wrapped.get(
                        "public_url_prefix"
                    ),
                    job_id=job_id,
                )

                jobs.append(
                    Job(
                        id=job_id,
                        title=title,
                        company=company.name,
                        location=location,
                        url=url,
                        posted_at=self._parse_date(
                            item.get("PostedDate")
                        ),
                        department=department,
                    )
                )

            except (
                KeyError,
                TypeError,
                ValueError,
            ):
                continue

        return jobs

    def validate(
        self,
        company: Company,
    ) -> bool:
        config = company.provider.config

        if not config.host:
            return False

        enabled_sites = [
            site
            for site in config.sites
            if site.enabled
        ]

        if not enabled_sites:
            return False

        site = enabled_sites[0]

        url = self._listing_url(company)

        finder = (
            "findReqs;"
            f"siteNumber={site.site_number},"
            "limit=1,"
            "offset=0"
        )

        response = requests.get(
            url,
            params={
                "onlyData": "true",
                "expand": "requisitionList",
                "finder": finder,
            },
            headers=self._headers(),
            timeout=_TIMEOUT,
        )

        self._check_response(
            response,
            company,
        )

        data = response.json()
        items = data.get("items") or []

        if not items:
            return False

        root = items[0]

        return (
            "TotalJobsCount" in root
            and "requisitionList" in root
        )