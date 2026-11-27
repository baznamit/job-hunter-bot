from datetime import datetime
import json
from urllib.parse import quote, unquote

import requests

from models import Job
from models.company import Company

from .base import ProviderAdapter

_TIMEOUT = 20
_DEFAULT_API_BASE = "https://thapi.azurewebsites.net"


class TurboHireAdapter(ProviderAdapter):
    """Adapter for TurboHire's public career page job feed."""

    provider_name = "TurboHire"

    @staticmethod
    def _site_url(company: Company) -> str:
        base_url = company.provider.config.base_url
        if not base_url:
            raise ValueError(
                f"{company.name}: TurboHire requires config.base_url"
            )
        return base_url.rstrip("/")

    @staticmethod
    def _account_name(company: Company) -> str:
        return company.provider.config.organization or company.id

    def _fetch_raw(self, company: Company) -> dict:
        site_url = self._site_url(company)
        api_base = (
            company.provider.config.api_url or _DEFAULT_API_BASE
        ).rstrip("/")
        headers = {
            "Origin": site_url,
            "Referer": site_url + "/",
            "User-Agent": "Mozilla/5.0 (compatible; JobHunterBot/1.0)",
            "Accept": "application/json, text/plain, */*",
        }

        token_response = requests.get(
            f"{api_base}/api/token/noauth",
            headers=headers,
            timeout=_TIMEOUT,
        )
        self._check_response(token_response, company)
        try:
            token_data = token_response.json()
        except requests.exceptions.JSONDecodeError as exc:
            raise RuntimeError(
                f"{company.name}: TurboHire token endpoint returned non-JSON"
            ) from exc
        token = token_data.get("access_token") if isinstance(token_data, dict) else None
        if not isinstance(token, str) or not token:
            raise RuntimeError(
                f"{company.name}: TurboHire token response has no access token"
            )

        headers["Authorization"] = f"Bearer {token}"
        organization_response = requests.get(
            f"{api_base}/api/publicorganizations",
            params={"accountName": self._account_name(company)},
            headers=headers,
            timeout=_TIMEOUT,
        )
        self._check_response(organization_response, company)
        try:
            organization = organization_response.json()
        except requests.exceptions.JSONDecodeError as exc:
            raise RuntimeError(
                f"{company.name}: TurboHire organization endpoint returned non-JSON"
            ) from exc
        org_id = organization.get("OrgID") if isinstance(organization, dict) else None
        if not isinstance(org_id, str) or not org_id:
            raise RuntimeError(
                f"{company.name}: TurboHire organization response has no OrgID"
            )

        jobs_response = requests.post(
            f"{api_base}/api/careerpagev2/filteredjobs",
            params={"orgId": org_id, "pageType": 0},
            json={},
            headers={
                **headers,
                "Content-Type": "application/json",
            },
            timeout=_TIMEOUT,
        )
        self._check_response(jobs_response, company)
        try:
            raw = jobs_response.json()
        except requests.exceptions.JSONDecodeError as exc:
            raise RuntimeError(
                f"{company.name}: TurboHire jobs endpoint returned non-JSON"
            ) from exc
        if not isinstance(raw, dict) or not isinstance(raw.get("Result"), list):
            raise RuntimeError(
                f"{company.name}: TurboHire jobs endpoint returned an unexpected response shape"
            )
        return raw

    @staticmethod
    def _location(value: object) -> str:
        locations: object = value
        if isinstance(value, str):
            try:
                locations = json.loads(value)
            except (ValueError, TypeError):
                return value.strip() or "Unknown"

        if isinstance(locations, list):
            names = [
                item.get("Address", "").strip()
                for item in locations
                if isinstance(item, dict)
                and isinstance(item.get("Address"), str)
                and item.get("Address", "").strip()
            ]
            if names:
                return ", ".join(dict.fromkeys(names))
        if isinstance(locations, dict):
            address = locations.get("Address")
            if isinstance(address, str) and address.strip():
                return address.strip()
        return "Unknown"

    @staticmethod
    def _posted_at(value: object) -> datetime | None:
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    @staticmethod
    def _job_url(company: Company, item: dict) -> str:
        obfuscated_id = item.get("JobIdObfuscated")
        if isinstance(obfuscated_id, str) and obfuscated_id:
            # The API returns percent-escaped values; unquote first so the
            # final path encodes each path segment exactly once.
            job_id = quote(unquote(obfuscated_id), safe="")
        else:
            job_id = quote(str(item["JobId"]), safe="")
        return f"{TurboHireAdapter._site_url(company)}/job/publicjobs/{job_id}"

    def parse(self, raw: dict, company: Company) -> list[Job]:
        records = raw.get("Result")
        if not isinstance(records, list):
            return []

        jobs: list[Job] = []
        for item in records:
            if not isinstance(item, dict):
                continue
            job_id = item.get("JobId")
            title = item.get("JobTitle")
            if not job_id or not title:
                continue
            try:
                jobs.append(
                    Job(
                        id=str(job_id),
                        title=str(title).strip(),
                        company=company.name,
                        location=self._location(item.get("Location")),
                        url=self._job_url(company, item),
                        posted_at=self._posted_at(item.get("PublishedDate")),
                        department=item.get("Department") or None,
                        employment_type=item.get("EmploymentType") or None,
                    )
                )
            except (TypeError, ValueError, KeyError):
                continue
        return jobs

    def validate(self, company: Company) -> bool:
        raw = self._fetch_raw(company)
        total = raw.get("Total")
        return isinstance(total, int) and total >= len(raw["Result"])
