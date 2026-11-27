from __future__ import annotations

from datetime import datetime
from urllib.parse import urlsplit

import requests

from models import Job
from models.company import Company
from .base import ProviderAdapter

API = (
    "https://careers.publicissapient.com"
    "/bin/ps-redesign/careersJobsearch"
)

BASE = "https://careers.publicissapient.com"
DETAIL_PREFIX = "/job-details/"
TIMEOUT = (10, 30)
DEFAULT_PAGE_SIZE = 20
DEFAULT_MAX_PAGES = 10
DEFAULT_COUNTRY = "India"


class PublicisSapientAdapter(ProviderAdapter):
    """
    Publicis Sapient careers search (Solr-backed JSON, iCIMS apply flow).

    The search index returns one document per advertised city. Documents
    for the same requisition share ``jobId``; the primary document has
    ``id == jobId`` and additional cities use ``id == f"{jobId}-<n>"``.
    Records are grouped by ``jobId`` so each requisition produces one Job
    carrying every advertised location, leaving location eligibility to
    the central filter.
    """

    provider_name = "Publicis Sapient"

    @staticmethod
    def _params(country: str, start: int, rows: int) -> dict:
        return {
            "country": country,
            "start": start,
            "rows": rows,
            "searchType": "/search",
            "lang": "en",
            "q": "",
        }

    @staticmethod
    def _positive_int(value, default: int, name: str, company: Company) -> int:
        if value is None:
            return default
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(
                f"{company.name}: {name} must be a positive integer"
            )
        return value

    @staticmethod
    def _text(value) -> str:
        if value is None or isinstance(value, (dict, list, bool)):
            return ""
        return " ".join(str(value).split())

    @classmethod
    def _validate_doc(cls, doc) -> tuple[str, str]:
        if not isinstance(doc, dict):
            raise RuntimeError("Invalid Publicis Sapient record")

        doc_id = cls._text(doc.get("id"))
        job_id = cls._text(doc.get("jobId"))

        if not doc_id or not job_id:
            raise RuntimeError(
                "Missing Publicis Sapient document ID or jobId"
            )

        if doc_id != job_id and not doc_id.startswith(job_id + "-"):
            raise RuntimeError(
                "Publicis Sapient document ID does not belong to "
                f"its requisition: id={doc_id!r} jobId={job_id!r}"
            )

        return doc_id, job_id

    def _fetch_raw(self, company: Company) -> list:
        cfg = company.provider.config
        endpoint = cfg.api_url or API

        if endpoint != API:
            raise ValueError("Unexpected Publicis Sapient API endpoint")

        rows = self._positive_int(
            cfg.page_size, DEFAULT_PAGE_SIZE, "page_size", company
        )
        max_pages = self._positive_int(
            cfg.max_pages, DEFAULT_MAX_PAGES, "max_pages", company
        )
        country = (cfg.search_location or DEFAULT_COUNTRY).strip()

        if not country:
            raise ValueError(
                f"{company.name}: search_location must not be empty"
            )

        collected: dict[str, dict] = {}
        page_signatures: set[frozenset[str]] = set()
        total = None
        pages_fetched = 0
        raw_records = 0
        completed = False

        try:
            with requests.Session() as session:
                session.headers.update({
                    "User-Agent": "Mozilla/5.0",
                    "Accept": "application/json",
                    "Referer": BASE + "/job-search",
                })

                for page in range(max_pages):
                    start = page * rows
                    response = session.get(
                        endpoint,
                        params=self._params(country, start, rows),
                        timeout=TIMEOUT,
                    )
                    pages_fetched += 1
                    self._check_response(response, company)

                    if "json" not in response.headers.get(
                        "Content-Type", ""
                    ).lower():
                        raise RuntimeError(
                            "Publicis Sapient returned non-JSON"
                        )

                    data = response.json()
                    result = (
                        data.get("response")
                        if isinstance(data, dict)
                        else None
                    )

                    if not isinstance(result, dict):
                        raise RuntimeError(
                            "Invalid Publicis Sapient response"
                        )

                    reported = result.get("numFound")
                    docs = result.get("docs")

                    if (
                        isinstance(reported, bool)
                        or not isinstance(reported, int)
                        or reported < 0
                    ):
                        raise RuntimeError(
                            "Publicis Sapient invalid numFound: "
                            f"page={page} "
                            f"value_type={type(reported).__name__}"
                        )

                    if result.get("numFoundExact") is not True:
                        raise RuntimeError(
                            "Publicis Sapient total is not exact"
                        )

                    if result.get("start") != start:
                        raise RuntimeError(
                            "Publicis Sapient returned unexpected "
                            f"offset: requested={start} "
                            f"received={result.get('start')!r}"
                        )

                    if not isinstance(docs, list):
                        raise RuntimeError(
                            "Publicis Sapient invalid docs: "
                            f"page={page} "
                            f"type={type(docs).__name__}"
                        )

                    raw_records += len(docs)

                    if total is None:
                        total = reported

                    if total != reported:
                        raise RuntimeError(
                            "Publicis Sapient inventory changed "
                            "during pagination"
                        )

                    if total == 0:
                        if docs:
                            raise RuntimeError(
                                "Publicis Sapient returned records "
                                "for an empty inventory"
                            )
                        break

                    if not docs:
                        raise RuntimeError(
                            "Publicis Sapient returned an empty "
                            "page before inventory completion"
                        )

                    if len(docs) > rows:
                        raise RuntimeError(
                            "Publicis Sapient returned more records "
                            "than requested"
                        )

                    page_docs = [
                        (self._validate_doc(doc)[0], doc)
                        for doc in docs
                    ]
                    signature = frozenset(
                        doc_id for doc_id, _ in page_docs
                    )

                    if signature in page_signatures:
                        raise RuntimeError(
                            "Publicis Sapient pagination stalled: "
                            f"page={page} repeated document page"
                        )

                    page_signatures.add(signature)

                    if len(signature) != len(page_docs) or any(
                        doc_id in collected for doc_id in signature
                    ):
                        raise RuntimeError(
                            "Publicis Sapient returned duplicate "
                            f"document IDs: page={page}"
                        )

                    for doc_id, doc in page_docs:
                        collected[doc_id] = doc

                    if len(collected) > total:
                        raise RuntimeError(
                            "Publicis Sapient returned more records "
                            "than reported"
                        )

                    if len(collected) == total:
                        break

                if total is not None and len(collected) < total:
                    raise RuntimeError(
                        "Publicis Sapient inventory incomplete: "
                        f"received {len(collected)}/{total} records "
                        f"within {max_pages} pages"
                    )

            completed = True
        finally:
            requisitions = len({
                self._text(doc.get("jobId"))
                for doc in collected.values()
            })
            self._emit_diagnostic(
                f"  [PUBLICIS] {company.name}: "
                f"status={'complete' if completed else 'failed'} "
                f"pages={pages_fetched} raw_records={raw_records} "
                f"records={len(collected)} total={total} "
                f"requisitions={requisitions}"
            )

        return list(collected.values())

    @staticmethod
    def _date(value):
        if not isinstance(value, str) or not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    @classmethod
    def _job_url(cls, doc: dict) -> str:
        path = cls._text(doc.get("jobDetailUrl"))

        if path.startswith(BASE + DETAIL_PREFIX):
            path = path[len(BASE):]

        parts = urlsplit(path)

        if (
            not path.startswith(DETAIL_PREFIX)
            or len(path) <= len(DETAIL_PREFIX)
            or parts.scheme
            or parts.netloc
            or parts.query
            or parts.fragment
            or " " in path
            or "/" in path[len(DETAIL_PREFIX):]
        ):
            raise ValueError("Missing or malformed Publicis Sapient job URL")

        return BASE + path

    @classmethod
    def _location(cls, doc: dict) -> str:
        display = cls._text(doc.get("displayLocation"))
        if display:
            return display
        return ", ".join(
            part
            for part in (
                cls._text(doc.get("city")),
                cls._text(doc.get("region")),
                cls._text(doc.get("countryName")),
            )
            if part
        )

    def parse(self, raw: dict | list, company: Company) -> list[Job]:
        if not isinstance(raw, list):
            raise ValueError("Expected Publicis Sapient record list")

        groups: dict[str, list[tuple[str, dict]]] = {}

        for doc in raw:
            try:
                doc_id, job_id = self._validate_doc(doc)
            except RuntimeError as exc:
                raise ValueError(str(exc)) from exc
            groups.setdefault(job_id, []).append((doc_id, doc))

        jobs = []

        for job_id, records in groups.items():
            records = sorted(
                {doc_id: doc for doc_id, doc in records}.items(),
                key=lambda item: (item[0] != job_id, item[0]),
            )
            primary = records[0][1]
            title = self._text(primary.get("name"))

            if not title:
                raise ValueError(
                    f"Missing Publicis Sapient title: jobId={job_id!r}"
                )

            locations = []
            for _, doc in records:
                location = self._location(doc)
                if location and location not in locations:
                    locations.append(location)

            jobs.append(Job(
                id=job_id,
                title=title,
                company=company.name,
                location=" | ".join(locations) or "Unknown",
                url=self._job_url(primary),
                posted_at=self._date(primary.get("releasedDate")),
                department=self._text(primary.get("teams")) or None,
                employment_type=(
                    self._text(primary.get("typeOfEmployment")) or None
                ),
                remote=False,
            ))

        return jobs
