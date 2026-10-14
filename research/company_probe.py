
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from urllib.parse import urlparse, parse_qs

import requests


TIMEOUT = (10, 40)
MAX_BYTES = 12_000_000

HCL_URL = (
    "https://careers.hcltech.com"
    "/services/recruiting/v1/jobs"
)

IBM_URL = (
    "https://www-api.ibm.com"
    "/search/api/v2"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/127.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Content-Type": "application/json",
}


# ============================================================
# COMMON HTTP
# ============================================================

def post_json(session, label, url, payload):
    print(
        f"\n[{label}] "
        f"POST {url}"
    )

    try:
        with session.post(
            url,
            json=payload,
            timeout=TIMEOUT,
            stream=True,
        ) as response:

            print(
                f"[{label}] "
                f"status={response.status_code} "
                f"type={response.headers.get('Content-Type')} "
                f"final={response.url}"
            )

            if response.status_code != 200:
                print(
                    f"[{label}] "
                    f"HTTP_ERROR={response.status_code}"
                )
                return None

            content_type = response.headers.get(
                "Content-Type", ""
            ).lower()

            if "json" not in content_type:
                print(
                    f"[{label}] "
                    "INVALID_CONTENT_TYPE"
                )
                return None

            chunks = []
            size = 0

            for chunk in response.iter_content(
                chunk_size=65536
            ):
                if not chunk:
                    continue

                size += len(chunk)

                if size > MAX_BYTES:
                    print(
                        f"[{label}] "
                        "RESPONSE_TOO_LARGE"
                    )
                    return None

                chunks.append(chunk)

            try:
                return json.loads(
                    b"".join(chunks)
                )
            except ValueError as exc:
                print(
                    f"[{label}] "
                    f"INVALID_JSON={exc}"
                )
                return None

    except requests.RequestException as exc:
        print(
            f"[{label}] "
            f"REQUEST_ERROR="
            f"{type(exc).__name__}: {exc}"
        )
        return None


# ============================================================
# HCLTECH
# ============================================================

def hcl_payload(
    page_number=0,
    keywords="java",
):
    return {
        "locale": "en_US",
        "pageNumber": page_number,
        "sortBy": "",
        "keywords": keywords,
        "location": "",
        "facetFilters": {},
        "categoryId": 0,
        "brand": "",
        "alertId": "",
        "rcmCandidateId": "",
        "skills": [],
    }


def parse_hcl(payload, label):
    if not isinstance(payload, dict):
        print(
            f"[{label}] INVALID_ROOT"
        )
        return set()

    records = payload.get(
        "jobSearchResult"
    )

    total = payload.get(
        "totalJobs"
    )

    print(
        f"[{label}] "
        f"totalJobs={total} "
        f"records_type={type(records).__name__}"
    )

    if not isinstance(records, list):
        return set()

    ids = set()
    locations = Counter()

    for record in records:
        if not isinstance(record, dict):
            continue

        job = record.get(
            "response", {}
        )

        if not isinstance(job, dict):
            continue

        job_id = str(
            job.get("id") or ""
        ).strip()

        if job_id:
            ids.add(job_id)

        location = str(
            job.get("custprimecity") or ""
        ).strip()

        if location:
            locations[location] += 1

    print(
        f"[{label}] "
        f"records={len(records)} "
        f"unique_ids={len(ids)} "
        f"locations={locations.most_common(12)}"
    )

    for record in records[:5]:
        job = record.get("response", {})

        print(
            f"[{label}] JOB "
            f"id={job.get('id')} "
            f"title={job.get('unifiedStandardTitle')} "
            f"location={job.get('custprimecity')}"
        )

    return ids


def probe_hcl(session):
    print(
        "\n========== HCLTECH =========="
    )

    results = {}

    cases = (
        ("HCL-JAVA-P0", 0, "java"),
        ("HCL-JAVA-P1", 1, "java"),
        ("HCL-ALL-P0", 0, ""),
        ("HCL-ALL-P1", 1, ""),
    )

    for label, page, keyword in cases:
        payload = hcl_payload(
            page_number=page,
            keywords=keyword,
        )

        response = post_json(
            session,
            label,
            HCL_URL,
            payload,
        )

        if response is None:
            results[label] = None
            continue

        results[label] = parse_hcl(
            response,
            label,
        )

    for first, second in (
        ("HCL-JAVA-P0", "HCL-JAVA-P1"),
        ("HCL-ALL-P0", "HCL-ALL-P1"),
    ):
        a = results.get(first)
        b = results.get(second)

        if a is None or b is None:
            continue

        print(
            f"[HCL-COMPARE] "
            f"{first} vs {second} "
            f"overlap={len(a & b)} "
            f"distinct={a != b}"
        )


# ============================================================
# IBM
# ============================================================

IBM_FIELDS = [
    "keywords^1",
    "body^1",
    "url^2",
    "description^2",
    "h1s_content^2",
    "title^3",
    "field_text_01",
]

IBM_SOURCE = [
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


def ibm_aggregations():
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


def ibm_payload(
    page=1,
    keyword="Java",
):
    size = 30

    return {
        "appId": "careers",
        "scopes": ["careers2"],
        "query": {
            "bool": {
                "must": [
                    {
                        "simple_query_string": {
                            "query": keyword,
                            "fields": IBM_FIELDS,
                        }
                    }
                ]
            }
        },
        "aggs": ibm_aggregations(),
        "from": (page - 1) * size,
        "p": page,
        "size": size,
        "sort": [
            {"_score": "desc"},
            {"pageviews": "desc"},
        ],
        "lang": "zz",
        "localeSelector": {},
        "sm": {
            "query": keyword,
            "lang": "zz",
        },
        "_source": IBM_SOURCE,
    }


def parse_ibm(payload, label):
    if not isinstance(payload, dict):
        print(
            f"[{label}] INVALID_ROOT"
        )
        return set()

    hits_obj = payload.get(
        "hits", {}
    )

    if not isinstance(hits_obj, dict):
        print(
            f"[{label}] INVALID_HITS"
        )
        return set()

    total = hits_obj.get(
        "total", {}
    )

    records = hits_obj.get(
        "hits", []
    )

    print(
        f"[{label}] "
        f"total={total} "
        f"records={len(records)}"
    )

    ids = set()
    locations = Counter()

    for record in records:
        if not isinstance(record, dict):
            continue

        source = record.get(
            "_source", {}
        )

        if not isinstance(source, dict):
            continue

        url = str(
            source.get("url") or ""
        )

        query = parse_qs(
            urlparse(url).query
        )

        job_id = (
            query.get("jobId") or [None]
        )[0]

        if job_id:
            ids.add(str(job_id))

        location = str(
            source.get("field_keyword_19") or ""
        ).strip()

        if location:
            locations[location] += 1

    print(
        f"[{label}] "
        f"unique_job_ids={len(ids)} "
        f"locations={locations.most_common(12)}"
    )

    for record in records[:5]:
        source = record.get(
            "_source", {}
        )

        print(
            f"[{label}] JOB "
            f"title={source.get('title')} "
            f"location={source.get('field_keyword_19')} "
            f"url={source.get('url')}"
        )

    return ids


def probe_ibm(session):
    print(
        "\n========== IBM =========="
    )

    results = {}

    cases = (
        ("IBM-JAVA-P1", 1, "Java"),
        ("IBM-JAVA-P2", 2, "Java"),
    )

    for label, page, keyword in cases:
        response = post_json(
            session,
            label,
            IBM_URL,
            ibm_payload(
                page=page,
                keyword=keyword,
            ),
        )

        if response is None:
            results[label] = None
            continue

        results[label] = parse_ibm(
            response,
            label,
        )

    first = results.get(
        "IBM-JAVA-P1"
    )

    second = results.get(
        "IBM-JAVA-P2"
    )

    if first is not None and second is not None:
        print(
            "[IBM-COMPARE] "
            f"overlap={len(first & second)} "
            f"distinct={first != second}"
        )


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--company",
        choices=("all", "hcl", "ibm"),
        default="all",
    )

    args = parser.parse_args()

    with requests.Session() as session:
        session.headers.update(HEADERS)

        if args.company in ("all", "hcl"):
            probe_hcl(session)

        if args.company in ("all", "ibm"):
            probe_ibm(session)

    print(
        "\n[API-PROBE] Finished"
    )


if __name__ == "__main__":
    main()
