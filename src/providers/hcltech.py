from __future__ import annotations

from datetime import datetime

import requests

from models import Job
from models.company import Company
from src.hcltech_urls import canonical_hcltech_job_url
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
        slug = (
            item.get("unifiedUrlTitle")
            or item.get("urlTitle")
            or ""
        )
        return canonical_hcltech_job_url(
            item.get("id"),
            slug,
        )

    def _fetch_raw(self, company: Company) -> list:
        cfg = company.provider.config
        terms = cfg.search_terms or ["java"]
        max_pages = (
            cfg.max_pages
            if cfg.max_pages is not None
            else 15
        )

        if (
            isinstance(max_pages, bool)
            or not isinstance(max_pages, int)
            or max_pages < 1
        ):
            raise ValueError(
                f"{company.name}: max_pages must "
                "be a positive integer"
            )

        endpoint = cfg.api_url or API

        if endpoint != API:
            raise ValueError(
                "Unexpected HCLTech API endpoint"
            )

        collected = {}
        successful_terms = []

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
                page_signatures: set[frozenset[str]] = set()
                total = None
                received_hits = 0
                pages_fetched = 0
                raw_records = 0
                completed = False

                try:
                    for page in range(max_pages):
                        response = session.post(
                            endpoint,
                            json=self._payload(page, term),
                            timeout=TIMEOUT,
                        )
                        pages_fetched += 1
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
                                f"value_type={type(reported).__name__} "
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
                                f"keys={list(data.keys())}"
                            )

                        raw_records += len(records)

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

                        page_jobs = []

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

                            self._job_url(item)
                            page_jobs.append((job_id, item))

                        page_signature = frozenset(
                            job_id for job_id, _ in page_jobs
                        )

                        if page_signature in page_signatures:
                            raise RuntimeError(
                                "HCLTech pagination stalled: "
                                f"term={term!r} page={page} "
                                "repeated job-ID page"
                            )

                        page_signatures.add(page_signature)

                        for job_id, item in page_jobs:
                            term_jobs[job_id] = item

                        received_hits += len(records)

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
                    completed = True
                finally:
                    if completed:
                        successful_terms.append(
                            {
                                "pages": pages_fetched,
                                "raw_records": raw_records,
                                "processed_records": received_hits,
                                "total": total or 0,
                                "duplicates": (
                                    received_hits - len(term_jobs)
                                ),
                            }
                        )
                    else:
                        if successful_terms:
                            self._emit_diagnostic(
                                f"  [HCLTECH] {company.name}: "
                                f"terms={len(successful_terms)} "
                                "status=complete_before_failure "
                                f"pages={sum(item['pages'] for item in successful_terms)} "
                                f"raw_records={sum(item['raw_records'] for item in successful_terms)} "
                                f"processed_records={sum(item['processed_records'] for item in successful_terms)} "
                                f"total={sum(item['total'] for item in successful_terms)}"
                            )
                        self._emit_diagnostic(
                            f"  [HCLTECH] {company.name}: term={term!r} "
                            "status=failed "
                            f"pages={pages_fetched} raw_records={raw_records} "
                            f"processed_records={received_hits} total={total} "
                            f"unique={len(term_jobs)} "
                            f"duplicates={received_hits - len(term_jobs)}"
                        )

        self._emit_diagnostic(
            f"  [HCLTECH] {company.name}: "
            f"terms={len(successful_terms)} status=complete "
            f"pages={sum(item['pages'] for item in successful_terms)} "
            f"raw_records="
            f"{sum(item['raw_records'] for item in successful_terms)} "
            f"processed_records="
            f"{sum(item['processed_records'] for item in successful_terms)} "
            f"total={sum(item['total'] for item in successful_terms)} "
            f"unique={len(collected)} "
            f"duplicates="
            f"{sum(item['duplicates'] for item in successful_terms)}"
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