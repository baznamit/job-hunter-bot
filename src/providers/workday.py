import sys
import requests

from models import Job
from models.company import Company

from .base import ProviderAdapter

_TIMEOUT = 20
_PAGE_SIZE = 20


class WorkdayAdapter(ProviderAdapter):

    provider_name = "Workday"

    def _fetch_raw(self, company: Company) -> dict:
        config = company.provider.config
        tenant = config.tenant
        board = config.board
        cluster = config.cluster

        base = f"https://{tenant}.{cluster}.myworkdayjobs.com"
        url = f"{base}/wday/cxs/{tenant}/{board}/jobs"

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Origin": base,
            "Referer": f"{base}/en-US/{board}",
        }

        all_postings: list[dict] = []
        offset = 0

        while True:
            body = {
                "appliedFacets": {},
                "limit": _PAGE_SIZE,
                "offset": offset,
                "searchText": "",
            }

            response = requests.post(
                url,
                json=body,
                headers=headers,
                timeout=_TIMEOUT,
            )
            self._check_response(response, company)
            data = response.json()

            postings = data.get("jobPostings", [])
            total = data.get("total", 0)

            print(
                f"  [WORKDAY] {company.name}: "
                f"offset={offset}, "
                f"requested={_PAGE_SIZE}, "
                f"returned={len(postings)}, "
                f"total={total}",
                file=sys.stderr,
            )

            all_postings.extend(postings)

            if not postings:
                print(
                    f"  [WORKDAY] {company.name}: stopping — "
                    "provider returned no postings",
                    file=sys.stderr,
                )
                break

            offset += len(postings)

            if offset >= total:
                print(
                    f"  [WORKDAY] {company.name}: stopping — "
                    f"offset {offset} reached reported total {total}",
                    file=sys.stderr,
                )
                break

        print(
            f"  [WORKDAY] {company.name}: "
            f"pagination complete — {len(all_postings)} postings collected",
            file=sys.stderr,
        )
        
        return {"jobPostings": all_postings}

    def parse(self, raw: dict, company: Company) -> list[Job]:
        config = company.provider.config

        base = (
            f"https://{config.tenant}."
            f"{config.cluster}.myworkdayjobs.com"
        )

        jobs = []

        for item in raw.get("jobPostings", []):
            job = self._parse_item(
                item=item,
                company=company,
                base_url=base,
                board=config.board,
            )

            if job is not None:
                jobs.append(job)

        return jobs

    def _parse_item(
        self,
        item: dict,
        company: Company,
        base_url: str,
        board: str,
    ) -> Job | None:
        try:
            external_path = item.get("externalPath", "")

            # Workday's API returns externalPath without the public
            # career-site board prefix. Build the browser-facing URL
            # using the configured Workday board.
            if external_path:
                external_path = external_path.lstrip("/")
                url = f"{base_url}/en-US/{board}/{external_path}"
            else:
                url = f"{base_url}/en-US/{board}"

            location = item.get("locationsText") or "Unknown"
            department = item.get("businessTitle") or None
            employment_type = item.get("timeType") or None

            return Job(
                id=item.get("externalPath") or item["title"],
                title=item["title"],
                company=company.name,
                location=location,
                url=url,
                posted_at=None,
                department=department,
                employment_type=employment_type,
            )

        except Exception:
            return None

    def validate(self, company: Company) -> bool:
        """
        Validate a Workday tenant/cluster/board using one lightweight
        jobs API request rather than fetching every page.
        """

        config = company.provider.config

        if not config.tenant or not config.cluster or not config.board:
            return False

        base = (
            f"https://{config.tenant}."
            f"{config.cluster}.myworkdayjobs.com"
        )

        url = (
            f"{base}/wday/cxs/"
            f"{config.tenant}/{config.board}/jobs"
        )

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Origin": base,
            "Referer": f"{base}/en-US/{config.board}",
        }

        response = requests.post(
            url,
            json={
                "appliedFacets": {},
                "limit": 1,
                "offset": 0,
                "searchText": "",
            },
            headers=headers,
            timeout=_TIMEOUT,
        )

        self._check_response(response, company)

        data = response.json()

        # A valid Workday jobs endpoint normally returns these fields.
        if not isinstance(data, dict):
            return False

        if "jobPostings" not in data and "total" not in data:
            return False

        return True