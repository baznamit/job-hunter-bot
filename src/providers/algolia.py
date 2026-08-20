from urllib.parse import urljoin

import requests

from models import Job
from models.company import Company

from .base import ProviderAdapter


_TIMEOUT = 30
_MAX_PAGES = 100


class AlgoliaAdapter(ProviderAdapter):
    provider_name = "Algolia"

    def _endpoint(
        self,
        company: Company,
    ) -> str:
        config = company.provider.config

        if not config.app_id:
            raise ValueError(
                f"{company.name}: Algolia provider "
                "requires app_id"
            )

        return (
            f"https://{config.app_id.lower()}"
            "-dsn.algolia.net/1/indexes/*/queries"
        )

    def _headers(
        self,
        company: Company,
    ) -> dict[str, str]:
        config = company.provider.config

        if not config.app_id:
            raise ValueError(
                f"{company.name}: Algolia provider "
                "requires app_id"
            )

        if not config.api_key:
            raise ValueError(
                f"{company.name}: Algolia provider "
                "requires api_key"
            )

        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Algolia-Application-Id": config.app_id,
            "X-Algolia-API-Key": config.api_key,
            "User-Agent": (
                "Mozilla/5.0 "
                "(compatible; JobHunterBot/1.0)"
            ),
        }

    def _fetch_page(
        self,
        company: Company,
        page: int,
    ) -> dict:
        config = company.provider.config

        if not config.index_name:
            raise ValueError(
                f"{company.name}: Algolia provider "
                "requires index_name"
            )

        page_size = config.page_size or 20

        response = requests.post(
            self._endpoint(company),
            headers=self._headers(company),
            json={
                "requests": [
                    {
                        "indexName": config.index_name,
                        "params": (
                            "query="
                            f"&hitsPerPage={page_size}"
                            f"&page={page}"
                        ),
                    }
                ]
            },
            timeout=_TIMEOUT,
        )

        self._check_response(
            response,
            company,
        )

        data = response.json()

        results = data.get("results") or []

        if not results:
            return {}

        return results[0]

    def _fetch_raw(
        self,
        company: Company,
    ) -> list[dict]:
        all_hits: list[dict] = []
        seen_ids: set[str] = set()

        total_pages: int | None = None

        for page in range(_MAX_PAGES):
            result = self._fetch_page(
                company,
                page,
            )

            if not result:
                break

            hits = result.get("hits") or []

            if not hits:
                break

            if total_pages is None:
                total_pages = result.get(
                    "nbPages"
                )

            new_hits = []

            for hit in hits:
                identifier = str(
                    hit.get("objectID")
                    or hit.get("ats_requisition_id")
                    or ""
                )

                if not identifier:
                    continue

                if identifier in seen_ids:
                    continue

                seen_ids.add(identifier)
                new_hits.append(hit)

            if not new_hits:
                break

            all_hits.extend(new_hits)

            if (
                total_pages is not None
                and page + 1 >= total_pages
            ):
                break

        else:
            raise RuntimeError(
                f"{company.name}: Algolia pagination "
                f"exceeded {_MAX_PAGES} pages"
            )

        return all_hits

    def parse(
        self,
        raw,
        company: Company,
    ) -> list[Job]:
        config = company.provider.config

        if not config.base_url:
            raise ValueError(
                f"{company.name}: Algolia provider "
                "requires base_url"
            )

        jobs: list[Job] = []

        for hit in raw:
            title = hit.get("title")

            if not title:
                continue

            job_id = (
                hit.get("ats_requisition_id")
                or hit.get("objectID")
            )

            if not job_id:
                continue

            location = (
                hit.get("display_location")
                or hit.get("location")
                or hit.get("town_city_country")
                or "Unknown"
            )

            path = hit.get("jd_url")

            if not path:
                continue

            url = urljoin(
                config.base_url.rstrip("/") + "/",
                path,
            )

            jobs.append(
                Job(
                    id=str(job_id),
                    title=str(title),
                    company=company.name,
                    location=str(location),
                    url=url,
                    department=(
                        hit.get("department")
                        or hit.get("category")
                    ),
                )
            )

        if company.id == "msci":
            india_jobs = [
                job
                for job in jobs
                if any(
                    marker in job.location.lower()
                    for marker in (
                        "india",
                        "mumbai",
                        "bengaluru",
                        "bangalore",
                        "goregaon",
                    )
                )
            ]

            software_jobs = [
                job
                for job in jobs
                if any(
                    marker in job.title.lower()
                    for marker in (
                        "software",
                        "developer",
                        "engineer",
                        "backend",
                        "java",
                        "platform",
                    )
                )
            ]

            print(
                "  [ALGOLIA-DIAG] "
                f"{company.name}: "
                f"parsed={len(jobs)}, "
                f"india_jobs={len(india_jobs)}, "
                f"software_jobs={len(software_jobs)}"
            )

            for job in india_jobs[:10]:
                print(
                    "  [ALGOLIA-DIAG] "
                    f"{company.name}: INDIA "
                    f"title={job.title!r}, "
                    f"location={job.location!r}, "
                    f"id={job.id!r}"
                )

            for job in software_jobs[:10]:
                print(
                    "  [ALGOLIA-DIAG] "
                    f"{company.name}: SOFTWARE "
                    f"title={job.title!r}, "
                    f"location={job.location!r}, "
                    f"id={job.id!r}"
                )

        return jobs

    def validate(
        self,
        company: Company,
    ) -> bool:
        try:
            result = self._fetch_page(
                company,
                0,
            )

            return bool(
                result.get("hits")
            )

        except (
            requests.RequestException,
            ValueError,
        ):
            return False