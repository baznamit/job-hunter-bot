from __future__ import annotations

import html
import re
from collections import Counter
from urllib.parse import urljoin

import requests

from models.company import (
    Company,
    ProviderStatus,
    ProviderType,
)
from src.providers.bankofamerica import (
    BankOfAmericaAdapter,
)


_TIMEOUT = 30

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/127.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/json;q=0.9,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


# =========================================================
# COMMON HELPERS
# =========================================================


def _clean(
    value: str,
) -> str:
    value = html.unescape(value)

    return re.sub(
        r"\s+",
        " ",
        value,
    ).strip()


def _print_response(
    company: str,
    label: str,
    response: requests.Response,
) -> None:
    print(
        f"[MUMBAI-PROBE] {company}: "
        f"{label} "
        f"status={response.status_code} "
        f"final={response.url} "
        f"content_type="
        f"{response.headers.get('Content-Type')} "
        f"server="
        f"{response.headers.get('Server')} "
        f"length={len(response.content)}"
    )


def _get(
    url: str,
) -> requests.Response:
    return requests.get(
        url,
        headers=_HEADERS,
        timeout=_TIMEOUT,
        allow_redirects=True,
    )


def _workday_post(
    *,
    tenant: str,
    cluster: str,
    board: str,
    offset: int,
    limit: int = 20,
) -> requests.Response:
    base = (
        f"https://{tenant}."
        f"{cluster}.myworkdayjobs.com"
    )

    url = (
        f"{base}/wday/cxs/"
        f"{tenant}/{board}/jobs"
    )

    return requests.post(
        url,
        json={
            "appliedFacets": {},
            "limit": limit,
            "offset": offset,
            "searchText": "",
        },
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Origin": base,
            "Referer": (
                f"{base}/en-US/{board}"
            ),
            "User-Agent": _HEADERS[
                "User-Agent"
            ],
        },
        timeout=_TIMEOUT,
    )


def _workday_jobs(
    response: requests.Response,
) -> tuple[list[dict], int | None]:
    try:
        payload = response.json()
    except requests.exceptions.JSONDecodeError:
        return [], None

    if not isinstance(
        payload,
        dict,
    ):
        return [], None

    jobs = (
        payload.get("jobPostings")
        or []
    )

    total = payload.get("total")

    if not isinstance(
        total,
        int,
    ):
        total = None

    return jobs, total


def _workday_key(
    item: dict,
) -> str:
    return str(
        item.get("externalPath")
        or item.get("title")
        or ""
    )


def _location_matches(
    item: dict,
    terms: tuple[str, ...],
) -> bool:
    location = str(
        item.get("locationsText")
        or ""
    ).lower()

    return any(
        term in location
        for term in terms
    )


# =========================================================
# BANK OF AMERICA
# =========================================================


def _bofa_company() -> Company:
    return Company.model_validate(
        {
            "id": "bank-of-america",
            "name": "Bank of America",
            "category": "Banking",
            "priority": 1,
            "career_page": (
                "https://careers."
                "bankofamerica.com/"
            ),
            "provider": {
                "type": "bankofamerica",
                "status": "implemented",
                "config": {
                    "base_url": (
                        "https://careers."
                        "bankofamerica.com"
                    ),
                },
            },
        }
    )


def probe_bank_of_america() -> None:
    name = "Bank of America"

    print()
    print(
        f"[MUMBAI-PROBE] {name}: START"
    )

    adapter = BankOfAmericaAdapter()
    company = _bofa_company()

    current_url = (
        "https://careers.bankofamerica.com/"
        "en-us/job-search/india"
    )

    seen_pages: set[str] = set()
    seen_ids: set[str] = set()

    location_counts: Counter[str] = Counter()

    # Ten pages are enough to determine the pagination
    # contract without turning the probe into another
    # production crawler.
    for page_number in range(
        1,
        11,
    ):
        if current_url in seen_pages:
            print(
                f"[MUMBAI-PROBE] {name}: "
                f"REPEATED_PAGE_URL={current_url}"
            )
            break

        seen_pages.add(
            current_url
        )

        response = _get(
            current_url
        )

        _print_response(
            name,
            f"page-{page_number}",
            response,
        )

        if response.status_code != 200:
            break

        page_html = response.text

        jobs = adapter._extract_jobs(
            page_html,
            company,
        )

        reported_total = (
            adapter._extract_total(
                page_html
            )
        )

        next_url = (
            adapter._extract_next_url(
                page_html,
                response.url,
            )
        )

        new_ids = 0

        for job in jobs:
            if job.id not in seen_ids:
                seen_ids.add(
                    job.id
                )
                new_ids += 1

            location_counts[
                job.location
            ] += 1

        print(
            f"[MUMBAI-PROBE] {name}: "
            f"page={page_number} "
            f"reported_total={reported_total} "
            f"jobs={len(jobs)} "
            f"new_ids={new_ids} "
            f"unique_ids={len(seen_ids)} "
            f"next={next_url}"
        )

        for job in jobs[:5]:
            print(
                f"[MUMBAI-PROBE] {name}: "
                f"JOB id={job.id!r} "
                f"title={job.title!r} "
                f"location={job.location!r} "
                f"url={job.url}"
            )

        if not next_url:
            break

        current_url = next_url

    print(
        f"[MUMBAI-PROBE] {name}: "
        f"pages_seen={len(seen_pages)} "
        f"unique_jobs={len(seen_ids)}"
    )

    print(
        f"[MUMBAI-PROBE] {name}: "
        f"top_locations="
        f"{location_counts.most_common(20)}"
    )

    india_like = sum(
        count
        for location, count
        in location_counts.items()
        if "india" in location.lower()
    )

    mumbai_like = sum(
        count
        for location, count
        in location_counts.items()
        if (
            "mumbai" in location.lower()
            or "navi mumbai"
            in location.lower()
        )
    )

    non_india = sum(
        count
        for location, count
        in location_counts.items()
        if (
            location != "Unknown"
            and "india"
            not in location.lower()
        )
    )

    print(
        f"[MUMBAI-PROBE] {name}: "
        f"india_like={india_like} "
        f"mumbai_like={mumbai_like} "
        f"non_india={non_india}"
    )

    # Compare one keyword route against the base India
    # route to verify the web-research finding that the
    # country restriction may fall back to global jobs.
    keyword_url = (
        "https://careers.bankofamerica.com/"
        "en-us/job-search/india/"
        "q-software-developer"
    )

    response = _get(
        keyword_url
    )

    _print_response(
        name,
        "keyword-software-developer",
        response,
    )

    if response.status_code == 200:
        jobs = adapter._extract_jobs(
            response.text,
            company,
        )

        total = adapter._extract_total(
            response.text
        )

        print(
            f"[MUMBAI-PROBE] {name}: "
            f"keyword_total={total} "
            f"keyword_page_jobs={len(jobs)}"
        )

        for job in jobs[:20]:
            print(
                f"[MUMBAI-PROBE] {name}: "
                f"KEYWORD_JOB "
                f"id={job.id!r} "
                f"title={job.title!r} "
                f"location={job.location!r}"
            )


# =========================================================
# MORNINGSTAR
# =========================================================


def _fetch_workday_inventory(
    *,
    company: str,
    tenant: str,
    cluster: str,
    board: str,
) -> tuple[
    dict[str, dict],
    int | None,
]:
    first = _workday_post(
        tenant=tenant,
        cluster=cluster,
        board=board,
        offset=0,
    )

    _print_response(
        company,
        f"{board}-offset-0",
        first,
    )

    if first.status_code != 200:
        return {}, None

    first_jobs, total = (
        _workday_jobs(first)
    )

    print(
        f"[MUMBAI-PROBE] {company}: "
        f"board={board!r} "
        f"page1={len(first_jobs)} "
        f"total={total}"
    )

    jobs_by_id: dict[
        str,
        dict,
    ] = {}

    for item in first_jobs:
        key = _workday_key(
            item
        )

        if key:
            jobs_by_id[key] = item

    if (
        total is None
        or total <= len(first_jobs)
    ):
        return jobs_by_id, total

    offset = len(first_jobs)

    # Morningstar is small enough that comparing the
    # complete boards is cheap and much more useful than
    # comparing only page 1.
    while offset < total:
        response = _workday_post(
            tenant=tenant,
            cluster=cluster,
            board=board,
            offset=offset,
        )

        if response.status_code != 200:
            _print_response(
                company,
                f"{board}-offset-{offset}",
                response,
            )
            break

        page, _ = _workday_jobs(
            response
        )

        if not page:
            break

        before = len(
            jobs_by_id
        )

        for item in page:
            key = _workday_key(
                item
            )

            if key:
                jobs_by_id[key] = item

        if len(jobs_by_id) == before:
            print(
                f"[MUMBAI-PROBE] {company}: "
                f"board={board!r} "
                f"PAGINATION_STALLED "
                f"offset={offset}"
            )
            break

        offset += len(page)

    return jobs_by_id, total


def probe_morningstar() -> None:
    name = "Morningstar"

    print()
    print(
        f"[MUMBAI-PROBE] {name}: START"
    )

    americas, americas_total = (
        _fetch_workday_inventory(
            company=name,
            tenant="morningstar",
            cluster="wd5",
            board="Americas",
        )
    )

    global_board, global_total = (
        _fetch_workday_inventory(
            company=name,
            tenant="morningstar",
            cluster="wd5",
            board="morningstar",
        )
    )

    americas_ids = set(
        americas
    )

    global_ids = set(
        global_board
    )

    intersection = (
        americas_ids
        & global_ids
    )

    only_americas = (
        americas_ids
        - global_ids
    )

    only_global = (
        global_ids
        - americas_ids
    )

    print(
        f"[MUMBAI-PROBE] {name}: "
        f"Americas reported_total="
        f"{americas_total} "
        f"fetched={len(americas)}"
    )

    print(
        f"[MUMBAI-PROBE] {name}: "
        f"morningstar reported_total="
        f"{global_total} "
        f"fetched={len(global_board)}"
    )

    print(
        f"[MUMBAI-PROBE] {name}: "
        f"intersection={len(intersection)} "
        f"only_Americas="
        f"{len(only_americas)} "
        f"only_morningstar="
        f"{len(only_global)}"
    )

    for label, inventory in (
        ("Americas", americas),
        ("morningstar", global_board),
    ):
        mumbai = [
            item
            for item
            in inventory.values()
            if _location_matches(
                item,
                (
                    "mumbai",
                    "navi mumbai",
                ),
            )
        ]

        india = [
            item
            for item
            in inventory.values()
            if _location_matches(
                item,
                (
                    "india",
                    "mumbai",
                    "pune",
                    "bengaluru",
                    "bangalore",
                    "hyderabad",
                    "gurugram",
                    "gurgaon",
                ),
            )
        ]

        print(
            f"[MUMBAI-PROBE] {name}: "
            f"board={label!r} "
            f"india_like={len(india)} "
            f"mumbai_like={len(mumbai)}"
        )

        for item in mumbai[:10]:
            print(
                f"[MUMBAI-PROBE] {name}: "
                f"board={label!r} "
                f"MUMBAI_JOB "
                f"title="
                f"{item.get('title')!r} "
                f"location="
                f"{item.get('locationsText')!r} "
                f"path="
                f"{item.get('externalPath')!r}"
            )

    for key in sorted(
        only_global
    )[:20]:
        item = global_board[
            key
        ]

        print(
            f"[MUMBAI-PROBE] {name}: "
            f"ONLY_morningstar "
            f"title={item.get('title')!r} "
            f"location="
            f"{item.get('locationsText')!r} "
            f"path={key!r}"
        )


# =========================================================
# ACCELYA
# =========================================================


def probe_accelya() -> None:
    name = "Accelya"

    print()
    print(
        f"[MUMBAI-PROBE] {name}: START"
    )

    first = _workday_post(
        tenant="accelya",
        cluster="wd103",
        board="Careers",
        offset=0,
    )

    _print_response(
        name,
        "offset-0",
        first,
    )

    if first.status_code != 200:
        print(
            f"[MUMBAI-PROBE] {name}: "
            f"body={first.text[:1500]!r}"
        )
        return

    page1, total = _workday_jobs(
        first
    )

    second = _workday_post(
        tenant="accelya",
        cluster="wd103",
        board="Careers",
        offset=20,
    )

    _print_response(
        name,
        "offset-20",
        second,
    )

    page2, total2 = (
        _workday_jobs(second)
    )

    ids1 = {
        _workday_key(item)
        for item in page1
        if _workday_key(item)
    }

    ids2 = {
        _workday_key(item)
        for item in page2
        if _workday_key(item)
    }

    print(
        f"[MUMBAI-PROBE] {name}: "
        f"total={total} "
        f"page1={len(page1)} "
        f"page2={len(page2)} "
        f"page2_total={total2} "
        f"pages_different="
        f"{ids1 != ids2} "
        f"overlap={len(ids1 & ids2)}"
    )

    combined = (
        page1
        + page2
    )

    for item in combined[:10]:
        print(
            f"[MUMBAI-PROBE] {name}: "
            f"JOB title="
            f"{item.get('title')!r} "
            f"location="
            f"{item.get('locationsText')!r} "
            f"posted="
            f"{item.get('postedOn')!r} "
            f"path="
            f"{item.get('externalPath')!r}"
        )

    relevant = [
        item
        for item in combined
        if _location_matches(
            item,
            (
                "mumbai",
                "pune",
                "india",
            ),
        )
    ]

    print(
        f"[MUMBAI-PROBE] {name}: "
        f"page1_2_india_mumbai_pune="
        f"{len(relevant)}"
    )

    if page1:
        path = page1[0].get(
            "externalPath"
        )

        if path:
            public_url = (
                "https://accelya."
                "wd103.myworkdayjobs.com/"
                "en-US/Careers/"
                f"{str(path).lstrip('/')}"
            )

            response = _get(
                public_url
            )

            _print_response(
                name,
                "public-job",
                response,
            )

            print(
                f"[MUMBAI-PROBE] {name}: "
                f"public_url={public_url}"
            )


# =========================================================
# WEATHERFORD / ORACLE CX
# =========================================================


def _interesting_urls(
    base_url: str,
    text: str,
) -> list[str]:
    candidates: set[str] = set()

    for value in re.findall(
        r'(?:href|src)=["\']'
        r'([^"\']+)["\']',
        text,
        flags=re.IGNORECASE,
    ):
        value = html.unescape(
            value
        )

        if value.startswith(
            (
                "#",
                "data:",
                "javascript:",
                "mailto:",
                "tel:",
            )
        ):
            continue

        candidates.add(
            urljoin(
                base_url,
                value,
            )
        )

    for value in re.findall(
        r'https?://[^"\'<>\s\\]+',
        text,
        flags=re.IGNORECASE,
    ):
        candidates.add(
            html.unescape(
                value
            ).rstrip(
                ".,);]}"
            )
        )

    interesting = []

    for url in candidates:
        lower = url.lower()

        if any(
            marker in lower
            for marker in (
                "oracle",
                "hcm",
                "career",
                "recruit",
                "job",
                "cx_1",
                "ocs.oraclecloud",
                "hcmrestapi",
            )
        ):
            interesting.append(
                url
            )

    return sorted(
        set(interesting)
    )


def _contexts(
    company: str,
    source: str,
    text: str,
) -> None:
    lower = text.lower()

    markers = (
        "CX_1",
        "recruitingCEJobRequisitions",
        "hcmRestApi",
        "oraclecloud",
        "ocs.oraclecloud",
        "siteNumber",
        "siteNumber=",
        "findReqs",
        "CandidateExperience",
        "fa.ocs",
    )

    for marker in markers:
        start = 0

        for _ in range(5):
            index = lower.find(
                marker.lower(),
                start,
            )

            if index < 0:
                break

            context = text[
                max(
                    0,
                    index - 700,
                ):
                index + 1800
            ]

            print(
                f"[MUMBAI-PROBE] {company}: "
                f"CONTEXT source={source} "
                f"marker={marker!r} "
                f"text={_clean(context)[:2500]!r}"
            )

            start = (
                index
                + len(marker)
            )


def probe_weatherford() -> None:
    name = "Weatherford"

    print()
    print(
        f"[MUMBAI-PROBE] {name}: START"
    )

    start_url = (
        "https://careers.weatherford.com/"
    )

    response = _get(
        start_url
    )

    _print_response(
        name,
        "career-root",
        response,
    )

    print(
        f"[MUMBAI-PROBE] {name}: "
        f"preview="
        f"{_clean(response.text[:1500])!r}"
    )

    _contexts(
        name,
        response.url,
        response.text,
    )

    urls = _interesting_urls(
        response.url,
        response.text,
    )

    print(
        f"[MUMBAI-PROBE] {name}: "
        f"interesting_urls={len(urls)}"
    )

    for url in urls[:50]:
        print(
            f"[MUMBAI-PROBE] {name}: "
            f"URL={url}"
        )

    scripts = [
        urljoin(
            response.url,
            html.unescape(src),
        )
        for src in re.findall(
            r'<script[^>]+src=["\']'
            r'([^"\']+)["\']',
            response.text,
            flags=re.IGNORECASE,
        )
    ]

    # Inspect only likely application/config scripts.
    # Avoid downloading every analytics/library asset.
    preferred = [
        url
        for url in scripts
        if any(
            marker in url.lower()
            for marker in (
                "candidate",
                "career",
                "oracle",
                "main",
                "app",
                "config",
            )
        )
    ]

    print(
        f"[MUMBAI-PROBE] {name}: "
        f"scripts={len(scripts)} "
        f"preferred_scripts="
        f"{len(preferred)}"
    )

    for script_url in preferred[:10]:
        try:
            script = _get(
                script_url
            )
        except requests.RequestException as exc:
            print(
                f"[MUMBAI-PROBE] {name}: "
                f"SCRIPT_FAILED "
                f"url={script_url} "
                f"error="
                f"{type(exc).__name__}: {exc}"
            )
            continue

        _print_response(
            name,
            "script",
            script,
        )

        if script.status_code != 200:
            continue

        _contexts(
            name,
            script.url,
            script.text,
        )

        for url in _interesting_urls(
            script.url,
            script.text,
        )[:30]:
            print(
                f"[MUMBAI-PROBE] {name}: "
                f"SCRIPT_URL={url}"
            )


# =========================================================


def main() -> None:
    print(
        "[MUMBAI-PROBE] "
        "Starting focused company research"
    )

    probe_bank_of_america()
    probe_morningstar()
    probe_accelya()
    probe_weatherford()

    print()
    print(
        "[MUMBAI-PROBE] Finished"
    )


if __name__ == "__main__":
    main()