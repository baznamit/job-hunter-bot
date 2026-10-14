from __future__ import annotations

from urllib.parse import urlparse, parse_qs

import requests

from models import Job
from models.company import Company
from .base import ProviderAdapter

API = "https://www-api.ibm.com/search/api/v2"
TIMEOUT = (10, 30)

FIELDS = [
    "keywords^1",
    "body^1",
    "url^2",
    "description^2",
    "h1s_content^2",
    "title^3",
    "field_text_01",
]

SOURCE = [
    "_id",
    "title",
    "url",
    "description",
    "language",
    "entitled",
    "field_keyword_17",
    "field_keyword_08",
    "field_keyword_18",
    "field_keyword_19",
]


class IBMAdapter(ProviderAdapter):
    provider_name = "IBM"

    @staticmethod
    def _aggregations() -> dict:
        result = {}

        for name, field, size in (
            ("field_keyword_172", "field_keyword_17", 6),
            ("field_keyword_083", "field_keyword_08", 6),
            ("field_keyword_184", "field_keyword_18", 6),
            ("field_keyword_055", "field_keyword_05", 1000),
        ):
            result[name] = {
                "filter": {"match_all": {}},
                "aggs": {
                    field: {
                        "terms": {
                            "field": field,
                            "size": size,
                        }
                    },
                    f"{field}_count": {
                        "cardinality": {
                            "field": field
                        }
                    },
                },
            }

        return result

    @classmethod
    def _payload(
        cls,
        term: str,
        page: int,
        size: int,
        offset: int | None = None,
    ):
        return {
            "appId": "careers",
            "scopes": ["careers2"],
            "query": {
                "bool": {
                    "must": [{
                        "simple_query_string": {
                            "query": term,
                            "fields": FIELDS,
                        }
                    }]
                }
            },
            "aggs": cls._aggregations(),
            "from": (
                offset
                if offset is not None
                else (page - 1) * size
            ),
            "p": page,
            "size": size,
            "sort": [
                {"_score": "desc"},
                {"pageviews": "desc"},
            ],
            "lang": "zz",
            "localeSelector": {},
            "sm": {
                "query": term,
                "lang": "zz",
            },
            "_source": SOURCE,
        }

    @staticmethod
    def _job_id(url: str) -> str:
        parsed = urlparse(url)

        if (
            parsed.scheme != "https"
            or parsed.hostname != "careers.ibm.com"
            or parsed.path != "/careers/JobDetail"
        ):
            raise ValueError(
                f"Unexpected IBM job URL: {url}"
            )

        job_id = parse_qs(
            parsed.query
        ).get("jobId", [""])[0]

        if not job_id.isdigit():
            raise ValueError(
                f"Missing IBM job ID: {url}"
            )

        return job_id

    def _fetch_raw(self, company: Company) -> list:
        cfg = company.provider.config

        terms = cfg.search_terms or [
            "Java",
            "Spring Boot",
            "Full Stack",
            "Backend",
            "Microservices",
        ]

        page_size = cfg.page_size or 30
        max_pages = cfg.max_pages or 15
        endpoint = cfg.api_url or API

        if endpoint != API:
            raise ValueError(
                "Unexpected IBM API endpoint"
            )

        if not 1 <= page_size <= 30:
            raise ValueError(
                "IBM page_size must be between 1 and 30"
            )

        collected = {}

        with requests.Session() as session:
            session.headers.update({
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Origin": "https://www.ibm.com",
                "Referer": "https://www.ibm.com/careers/search",
            })

            for term in terms:
                term_jobs = {}
                total = None
                offset = 0
                received_hits = 0
                duplicate_ids = 0

                for page in range(1, max_pages + 1):
                    response = session.post(
                        endpoint,
                        json=self._payload(
                            term,
                            page,
                            page_size,
                            offset,
                        ),
                        timeout=TIMEOUT,
                    )
                    self._check_response(
                        response, company
                    )

                    if "json" not in response.headers.get(
                        "Content-Type", ""
                    ).lower():
                        raise RuntimeError(
                            "IBM returned non-JSON"
                        )

                    data = response.json()

                    if not isinstance(data, dict):
                        raise RuntimeError(
                            "Invalid IBM response"
                        )

                    hits = data.get("hits")

                    if not isinstance(hits, dict):
                        raise RuntimeError(
                            "IBM response missing hits"
                        )

                    total_obj = hits.get("total")
                    records = hits.get("hits")

                    if (
                        not isinstance(total_obj, dict)
                        or not isinstance(
                            total_obj.get("value"), int
                        )
                        or not isinstance(records, list)
                    ):
                        raise RuntimeError(
                            "Invalid IBM search schema"
                        )

                    if total_obj.get("relation") != "eq":
                        raise RuntimeError(
                            "IBM total is not exact"
                        )

                    reported = total_obj["value"]

                    if total is None:
                        total = reported

                    if total != reported:
                        raise RuntimeError(
                            "IBM inventory changed "
                            "during pagination"
                        )

                    if total == 0:
                        break

                    if not records:
                        break

                    for record in records:
                        if not isinstance(record, dict):
                            raise RuntimeError(
                                "Invalid IBM hit"
                            )

                        item = record.get("_source")

                        if not isinstance(item, dict):
                            raise RuntimeError(
                                "IBM hit missing _source"
                            )

                        url = str(
                            item.get("url") or ""
                        )

                        job_id = self._job_id(url)

                        if job_id in term_jobs:
                            duplicate_ids += 1

                        term_jobs[job_id] = item

                    offset += len(records)

                    received_hits += len(records)

                    print(
                        f"[IBM-PAGE] term={term!r} "
                        f"page={page} "
                        f"hits={received_hits}/{total} "
                        f"unique={len(term_jobs)} "
                        f"duplicates={duplicate_ids}"
                    )

                    if received_hits >= total:
                        break

                if received_hits < total:
                    raise RuntimeError(
                        f"IBM query {term!r} incomplete: "
                        f"{received_hits}/{total} hits"
                    )

                collected.update(term_jobs)

                print(
                    f"  [IBM] {company.name}: "
                    f"term={term!r} total={total} "
                    f"unique={len(term_jobs)}"
                )

        return list(collected.values())

    def parse(
        self,
        raw: dict | list,
        company: Company,
    ) -> list[Job]:
        if not isinstance(raw, list):
            raise ValueError("Expected IBM job list")

        jobs = []
        seen = set()

        for item in raw:
            if not isinstance(item, dict):
                raise ValueError("Invalid IBM job")

            url = str(
                item.get("url") or ""
            ).strip()

            job_id = self._job_id(url)

            title = str(
                item.get("title") or ""
            ).strip()

            if not title:
                raise ValueError(
                    "IBM job missing title"
                )

            if job_id in seen:
                continue

            seen.add(job_id)

            location = " ".join(
                str(
                    item.get("field_keyword_19")
                    or "Unknown"
                ).split()
            )

            work_mode = str(
                item.get("field_keyword_17")
                or ""
            ).lower()

            jobs.append(Job(
                id=job_id,
                title=title,
                company=company.name,
                location=location,
                url=url,
                department=(
                    str(item["field_keyword_08"])
                    if item.get("field_keyword_08")
                    else None
                ),
                employment_type=(
                    str(item["field_keyword_18"])
                    if item.get("field_keyword_18")
                    else None
                ),
                remote=work_mode == "remote",
            ))

        return jobs