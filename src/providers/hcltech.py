from __future__ import annotations

from datetime import datetime
from urllib.parse import quote

import requests

from models import Job
from models.company import Company
from .base import ProviderAdapter

API = (
    "https://careers.hcltech.com"
    "/services/recruiting/v1/jobs"
)

BASE = "https://careers.hcltech.com"
TIMEOUT = (10, 30)


class HCLTechAdapter(ProviderAdapter):
    provider_name = "HCLTech"

    @staticmethod
    def _payload(page: int, keyword: str) -> dict:
        return {
            "locale": "en_US",
            "pageNumber": page,
            "sortBy": "",
            "keywords": keyword,
            "location": "",
            "facetFilters": {},
            "categoryId": 0,
            "brand": "",
            "alertId": "",
            "rcmCandidateId": "",
            "skills": [],
        }

    @staticmethod
    def _date(value):
        if not value:
            return None
        try:
            return datetime.strptime(
                str(value), "%m/%d/%y"
            )
        except ValueError:
            return None

    @staticmethod
    def _job_url(item: dict) -> str:
        job_id = str(item["id"]).strip()
        slug = str(
            item.get("unifiedUrlTitle")
            or item.get("urlTitle")
            or "job"
        ).strip().strip("/")

        return (
            f"{BASE}/job/"
            f"{quote(slug, safe='-')}/"
            f"{quote(job_id, safe='')}/"
        )

    def _fetch_raw(self, company: Company) -> list:
        cfg = company.provider.config
        terms = cfg.search_terms or ["java"]
        max_pages = cfg.max_pages or 15
        endpoint = cfg.api_url or API

        if endpoint != API:
            raise ValueError(
                "Unexpected HCLTech API endpoint"
            )

        collected = {}

        with requests.Session() as session:
            session.headers.update({
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Origin": BASE,
                "Referer": BASE + "/search/",
            })

            for term in terms:
                term_jobs = {}
                total = None
                received_hits = 0

                for page in range(max_pages):
                    response = session.post(
                        endpoint,
                        json=self._payload(page, term),
                        timeout=TIMEOUT,
                    )
                    self._check_response(response, company)

                    if "json" not in response.headers.get(
                        "Content-Type", ""
                    ).lower():
                        raise RuntimeError(
                            "HCLTech returned non-JSON"
                        )

                    data = response.json()

                    if not isinstance(data, dict):
                        raise RuntimeError(
                            "Invalid HCLTech response"
                        )

                    reported = data.get("totalJobs")
                    records = data.get("jobSearchResult")

                    if (
                        isinstance(reported, bool)
                        or not isinstance(reported, int)
                        or reported < 0
                    ):
                        raise RuntimeError(
                            f"HCLTech invalid totalJobs: "
                            f"term={term!r} page={page} "
                            f"value={reported!r} "
                            f"keys={list(data.keys())}"
                        )

                    if records is None and reported == 0:
                        records = []

                    if not isinstance(records, list):
                        raise RuntimeError(
                            f"HCLTech invalid jobSearchResult: "
                            f"term={term!r} page={page} "
                            f"totalJobs={reported} "
                            f"records_type={type(records).__name__} "
                            f"keys={list(data.keys())} "
                            f"preview={str(data)[:500]}"
                        )

                    if total is None:
                        total = reported

                    if total != reported:
                        raise RuntimeError(
                            "HCLTech inventory changed "
                            "during pagination"
                        )

                    if total == 0:
                        break

                    if not records:
                        raise RuntimeError(
                            "HCLTech returned an empty "
                            "page before inventory completion"
                        )

                    for record in records:
                        if not isinstance(record, dict):
                            raise RuntimeError(
                                "Invalid HCLTech record"
                            )

                        item = record.get("response")

                        if not isinstance(item, dict):
                            raise RuntimeError(
                                "Missing HCLTech job object"
                            )

                        job_id = str(
                            item.get("id") or ""
                        ).strip()

                        if not job_id:
                            raise RuntimeError(
                                "Missing HCLTech job ID"
                            )

                        term_jobs[job_id] = item

                    received_hits += len(records)

                    print(
                        f"[HCL-PAGE] term={term!r} "
                        f"page={page} "
                        f"received={received_hits}/{total} "
                        f"unique={len(term_jobs)}"
                    )

                    if received_hits >= total:
                        break

                if received_hits < total:
                    raise RuntimeError(
                        f"HCLTech query {term!r} "
                        f"incomplete: received "
                        f"{received_hits}/{total} records "
                        f"within {max_pages} pages; "
                        f"unique={len(term_jobs)}"
                    )

                collected.update(term_jobs)

                print(
                    f"  [HCLTECH] {company.name}: "
                    f"term={term!r} total={total} "
                    f"unique={len(term_jobs)}"
                )

        return list(collected.values())

    def parse(self, raw: dict | list, company: Company) -> list[Job]:
        if not isinstance(raw, list):
            raise ValueError("Expected HCLTech job list")

        jobs = []
        seen = set()

        for item in raw:
            if not isinstance(item, dict):
                raise ValueError("Invalid HCLTech job")

            job_id = str(item.get("id") or "").strip()
            title = str(
                item.get("unifiedStandardTitle") or ""
            ).strip()

            if not job_id or not title:
                raise ValueError(
                    "Missing HCLTech job ID or title"
                )

            if job_id in seen:
                continue

            seen.add(job_id)

            city = " ".join(
                str(
                    item.get("custprimecity") or ""
                ).split()
            )

            countries = item.get("custCountryRegion")
            country = ""

            if isinstance(countries, list):
                country = ", ".join(
                    str(x) for x in countries if x
                )

            location = ", ".join(
                x for x in (city, country) if x
            ) or "Unknown"

            jobs.append(Job(
                id=job_id,
                title=title,
                company=company.name,
                location=location,
                url=self._job_url(item),
                posted_at=self._date(
                    item.get("unifiedStandardStart")
                ),
                remote=False,
            ))

        return jobs