from __future__ import annotations

import html
import json
import re
from urllib.parse import (
    urljoin,
    urlparse,
)

import requests


_TIMEOUT = 30

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/127.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


# ============================================================
# COMMON
# ============================================================


def _clean(
    value: str,
) -> str:
    return re.sub(
        r"\s+",
        " ",
        html.unescape(value),
    ).strip()


def _get(
    url: str,
    *,
    params: dict | None = None,
) -> requests.Response:
    return requests.get(
        url,
        params=params,
        headers={
            **_HEADERS,
            "Accept": "*/*",
        },
        timeout=_TIMEOUT,
        allow_redirects=True,
    )


def _summary(
    prefix: str,
    label: str,
    response: requests.Response,
) -> None:
    print(
        f"[{prefix}] {label}: "
        f"status={response.status_code} "
        f"final={response.url} "
        f"content_type="
        f"{response.headers.get('Content-Type')!r} "
        f"server="
        f"{response.headers.get('Server')!r} "
        f"length={len(response.content)}"
    )


def _blocked(
    prefix: str,
    label: str,
    response: requests.Response,
) -> bool:
    final_url = str(
        response.url or ""
    ).lower()

    server = str(
        response.headers.get(
            "Server"
        )
        or ""
    ).lower()

    content_type = str(
        response.headers.get(
            "Content-Type"
        )
        or ""
    ).lower()

    preview = (
        response.text[:5000].lower()
        if (
            "text" in content_type
            or "html" in content_type
        )
        else ""
    )

    indicators = (
        "zscaler" in final_url,
        "zscaler" in server,
        "zscaler" in preview,
        "directory authentication"
        in preview,
        "smsamlq" in preview,
    )

    if not any(indicators):
        return False

    print(
        f"[{prefix}] {label}: "
        "BLOCKED_BY_NETWORK_SECURITY"
    )

    return True


def _extract_links(
    base_url: str,
    text: str,
) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    for href in re.findall(
        r'href=["\']([^"\']+)["\']',
        text,
        flags=re.IGNORECASE,
    ):
        href = html.unescape(
            href
        )

        if href.startswith(
            (
                "#",
                "javascript:",
                "mailto:",
                "tel:",
            )
        ):
            continue

        url = urljoin(
            base_url,
            href,
        )

        if url in seen:
            continue

        seen.add(url)
        result.append(url)

    return result


def _extract_scripts(
    base_url: str,
    text: str,
) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    for src in re.findall(
        r'<script[^>]+src=["\']'
        r'([^"\']+)["\']',
        text,
        flags=re.IGNORECASE,
    ):
        url = urljoin(
            base_url,
            html.unescape(src),
        )

        if url in seen:
            continue

        seen.add(url)
        result.append(url)

    return result


def _contexts(
    *,
    prefix: str,
    source: str,
    text: str,
    markers: tuple[str, ...],
    max_hits: int = 3,
    before: int = 1200,
    after: int = 2500,
) -> None:
    lower = text.lower()

    for marker in markers:
        needle = marker.lower()
        start = 0

        for _ in range(
            max_hits
        ):
            index = lower.find(
                needle,
                start,
            )

            if index < 0:
                break

            context = text[
                max(
                    0,
                    index - before,
                ):
                index + after
            ]

            print(
                f"[{prefix}] CONTEXT "
                f"source={source!r} "
                f"marker={marker!r} "
                f"text="
                f"{_clean(context)[:4000]!r}"
            )

            start = (
                index
                + len(needle)
            )


def _maharashtra_or_bengaluru(
    location: str,
) -> bool:
    lower = location.lower()

    return any(
        value in lower
        for value in (
            "mumbai",
            "navi mumbai",
            "pune",
            "maharashtra",
            "bangalore",
            "bengaluru",
        )
    )


# ============================================================
# WORKDAY
# ============================================================


def _workday_page(
    *,
    prefix: str,
    tenant: str,
    cluster: str,
    board: str,
    offset: int,
    limit: int = 20,
) -> dict | None:
    base = (
        f"https://{tenant}."
        f"{cluster}.myworkdayjobs.com"
    )

    url = (
        f"{base}/wday/cxs/"
        f"{tenant}/{board}/jobs"
    )

    response = requests.post(
        url,
        json={
            "appliedFacets": {},
            "limit": limit,
            "offset": offset,
            "searchText": "",
        },
        headers={
            **_HEADERS,
            "Content-Type":
                "application/json",
            "Accept":
                "application/json",
            "Origin": base,
            "Referer":
                f"{base}/en-US/{board}",
        },
        timeout=_TIMEOUT,
    )

    _summary(
        prefix,
        f"{board}-offset-{offset}",
        response,
    )

    if _blocked(
        prefix,
        board,
        response,
    ):
        return None

    if response.status_code != 200:
        print(
            f"[{prefix}] "
            f"{board} body="
            f"{response.text[:2000]!r}"
        )
        return None

    try:
        payload = response.json()
    except ValueError:
        print(
            f"[{prefix}] "
            f"{board}: NON_JSON "
            f"{response.text[:2000]!r}"
        )
        return None

    if not isinstance(
        payload,
        dict,
    ):
        print(
            f"[{prefix}] "
            f"{board}: "
            f"unexpected_type="
            f"{type(payload).__name__}"
        )
        return None

    postings = (
        payload.get(
            "jobPostings"
        )
        or []
    )

    print(
        f"[{prefix}] "
        f"board={board!r} "
        f"offset={offset} "
        f"total={payload.get('total')!r} "
        f"jobs={len(postings)} "
        f"keys={list(payload.keys())}"
    )

    for item in postings[:15]:
        print(
            f"[{prefix}] JOB "
            f"board={board!r} "
            f"title={item.get('title')!r} "
            f"location="
            f"{item.get('locationsText')!r} "
            f"posted="
            f"{item.get('postedOn')!r} "
            f"path="
            f"{item.get('externalPath')!r}"
        )

    return payload


def _workday_key(
    item: dict,
) -> str:
    return str(
        item.get(
            "externalPath"
        )
        or item.get("title")
        or ""
    )


def _compare_workday_pages(
    prefix: str,
    first: dict | None,
    second: dict | None,
) -> None:
    if (
        not isinstance(
            first,
            dict,
        )
        or not isinstance(
            second,
            dict,
        )
    ):
        return

    first_ids = {
        _workday_key(item)
        for item in (
            first.get(
                "jobPostings"
            )
            or []
        )
        if _workday_key(item)
    }

    second_ids = {
        _workday_key(item)
        for item in (
            second.get(
                "jobPostings"
            )
            or []
        )
        if _workday_key(item)
    }

    print(
        f"[{prefix}] "
        f"pagination_overlap="
        f"{len(first_ids & second_ids)} "
        f"pages_different="
        f"{first_ids != second_ids}"
    )


def _workday_location_scan(
    *,
    prefix: str,
    tenant: str,
    cluster: str,
    board: str,
    total: int,
    max_pages: int = 8,
) -> None:
    """
    Fetch a bounded number of pages only.

    This isn't intended to crawl the entire board. It gives
    enough evidence about India/Maharashtra/Bengaluru while
    keeping the research probe polite.
    """

    found: list[dict] = []

    pages = min(
        max_pages,
        max(
            1,
            (total + 19) // 20,
        ),
    )

    for page_number in range(
        pages
    ):
        offset = (
            page_number * 20
        )

        payload = _workday_page(
            prefix=prefix,
            tenant=tenant,
            cluster=cluster,
            board=board,
            offset=offset,
        )

        if not payload:
            break

        postings = (
            payload.get(
                "jobPostings"
            )
            or []
        )

        for item in postings:
            location = str(
                item.get(
                    "locationsText"
                )
                or ""
            )

            if (
                _maharashtra_or_bengaluru(
                    location
                )
            ):
                found.append(
                    item
                )

    print(
        f"[{prefix}] "
        f"sample_target_location_jobs="
        f"{len(found)}"
    )

    for item in found[:40]:
        print(
            f"[{prefix}] TARGET_JOB "
            f"title={item.get('title')!r} "
            f"location="
            f"{item.get('locationsText')!r} "
            f"path="
            f"{item.get('externalPath')!r}"
        )


# ============================================================
# DEUTSCHE BANK
# ============================================================


def probe_deutsche_bank() -> None:
    prefix = "DB-PROBE"

    print()
    print(
        f"[{prefix}] START"
    )

    first = _workday_page(
        prefix=prefix,
        tenant="db",
        cluster="wd3",
        board="DBWebsite",
        offset=0,
    )

    second = _workday_page(
        prefix=prefix,
        tenant="db",
        cluster="wd3",
        board="DBWebsite",
        offset=20,
    )

    _compare_workday_pages(
        prefix,
        first,
        second,
    )

    if isinstance(
        first,
        dict,
    ):
        total = first.get(
            "total"
        )

        if isinstance(
            total,
            int,
        ):
            _workday_location_scan(
                prefix=prefix,
                tenant="db",
                cluster="wd3",
                board="DBWebsite",
                total=total,
                max_pages=5,
            )

    # Known current requisition supplied manually.
    known_url = (
        "https://db.wd3."
        "myworkdayjobs.com/"
        "DBWebsite/job/"
        "Pune-Magarpatta-City-Hadapsa/"
        "Java-Full-Stack-Engineer--AVP_"
        "R0447756"
    )

    response = _get(
        known_url
    )

    _summary(
        prefix,
        "known-R0447756",
        response,
    )

    print(
        f"[{prefix}] "
        f"known_job_resolves="
        f"{response.status_code == 200} "
        f"final={response.url}"
    )

    # Optional DWS board.
    dws = _workday_page(
        prefix=prefix,
        tenant="db",
        cluster="wd3",
        board="DWSWebsite",
        offset=0,
    )

    if isinstance(
        dws,
        dict,
    ):
        print(
            f"[{prefix}] "
            f"DWS_total="
            f"{dws.get('total')!r}"
        )

        for item in (
            dws.get(
                "jobPostings"
            )
            or []
        ):
            location = str(
                item.get(
                    "locationsText"
                )
                or ""
            )

            if (
                _maharashtra_or_bengaluru(
                    location
                )
            ):
                print(
                    f"[{prefix}] "
                    f"DWS_TARGET "
                    f"title="
                    f"{item.get('title')!r} "
                    f"location={location!r} "
                    f"path="
                    f"{item.get('externalPath')!r}"
                )


# ============================================================
# TIAA
# ============================================================


def probe_tiaa() -> None:
    prefix = "TIAA-PROBE"

    print()
    print(
        f"[{prefix}] START"
    )

    first = _workday_page(
        prefix=prefix,
        tenant="tiaa",
        cluster="wd1",
        board="Search",
        offset=0,
    )

    second = _workday_page(
        prefix=prefix,
        tenant="tiaa",
        cluster="wd1",
        board="Search",
        offset=20,
    )

    _compare_workday_pages(
        prefix,
        first,
        second,
    )

    if isinstance(
        first,
        dict,
    ):
        total = first.get(
            "total"
        )

        if isinstance(
            total,
            int,
        ):
            _workday_location_scan(
                prefix=prefix,
                tenant="tiaa",
                cluster="wd1",
                board="Search",
                total=total,
                max_pages=8,
            )


# ============================================================
# SUCCESSFACTORS / RMK
# ============================================================


def _job_links(
    base_url: str,
    text: str,
) -> list[str]:
    return [
        link
        for link in _extract_links(
            base_url,
            text,
        )
        if "/job/" in link
    ]


def _probe_rmk_candidate(
    *,
    prefix: str,
    base_url: str,
    path: str,
) -> tuple[
    requests.Response | None,
    list[str],
]:
    url = urljoin(
        base_url.rstrip("/") + "/",
        path.lstrip("/"),
    )

    try:
        response = _get(
            url
        )
    except requests.RequestException as exc:
        print(
            f"[{prefix}] "
            f"path={path!r} "
            f"REQUEST_FAILED "
            f"{type(exc).__name__}: "
            f"{exc}"
        )

        return None, []

    _summary(
        prefix,
        f"candidate-{path}",
        response,
    )

    if _blocked(
        prefix,
        path,
        response,
    ):
        return response, []

    if response.status_code != 200:
        return response, []

    links = _job_links(
        response.url,
        response.text,
    )

    print(
        f"[{prefix}] "
        f"path={path!r} "
        f"job_links={len(links)}"
    )

    for link in links[:15]:
        print(
            f"[{prefix}] "
            f"JOB_LINK={link}"
        )

    return response, links


def _probe_rss(
    *,
    prefix: str,
    base_url: str,
) -> None:
    url = (
        base_url.rstrip("/")
        + "/services/rss/job/"
    )

    response = requests.get(
        url,
        params={
            "keywords": "",
            "locale": "en_US",
        },
        headers={
            **_HEADERS,
            "Accept": (
                "application/rss+xml,"
                "application/xml,"
                "text/xml;q=0.9,"
                "*/*;q=0.8"
            ),
        },
        timeout=_TIMEOUT,
        allow_redirects=True,
    )

    _summary(
        prefix,
        "rss",
        response,
    )

    if _blocked(
        prefix,
        "rss",
        response,
    ):
        return

    text = response.text

    item_count = len(
        re.findall(
            r"<item\b",
            text,
            flags=re.IGNORECASE,
        )
    )

    print(
        f"[{prefix}] "
        f"RSS_items={item_count}"
    )

    print(
        f"[{prefix}] "
        f"RSS_preview="
        f"{_clean(text[:5000])!r}"
    )


def _probe_rmk(
    *,
    prefix: str,
    base_url: str,
) -> None:
    print()
    print(
        f"[{prefix}] START "
        f"base={base_url}"
    )

    home = _get(
        base_url
    )

    _summary(
        prefix,
        "home",
        home,
    )

    if _blocked(
        prefix,
        "home",
        home,
    ):
        return

    text = home.text

    markers = (
        "successfactors",
        "careerSiteCompanyId",
        "careerSiteCompany",
        "company=",
        "career5.successfactors",
        "/search/",
        "/job/",
        "/services/rss/job/",
        "jobs2web",
        "rmk",
    )

    _contexts(
        prefix=prefix,
        source="home",
        text=text,
        markers=markers,
        max_hits=4,
    )

    # These are intentionally based on the URL pattern used
    # by the current production SuccessFactorsAdapter:
    #
    # base_url + listing_path + offset + "/"
    #
    # We need to discover which listing_path actually exposes
    # job links and whether offset pagination behaves that way.
    candidates = (
        "search/",
        "search/0/",
        "search/100/",
    )

    results: dict[
        str,
        list[str],
    ] = {}

    for path in candidates:
        _, links = (
            _probe_rmk_candidate(
                prefix=prefix,
                base_url=base_url,
                path=path,
            )
        )

        results[path] = links

    first = set(
        results.get(
            "search/",
            [],
        )
    )

    zero = set(
        results.get(
            "search/0/",
            [],
        )
    )

    hundred = set(
        results.get(
            "search/100/",
            [],
        )
    )

    print(
        f"[{prefix}] "
        f"search_vs_zero_same="
        f"{first == zero} "
        f"search_vs_100_overlap="
        f"{len(first & hundred)} "
        f"search_100_different="
        f"{bool(hundred) and first != hundred}"
    )

    _probe_rss(
        prefix=prefix,
        base_url=base_url,
    )

    scripts = _extract_scripts(
        home.url,
        text,
    )

    print(
        f"[{prefix}] "
        f"scripts={len(scripts)}"
    )

    for script in scripts[:30]:
        if any(
            marker in script.lower()
            for marker in (
                "career",
                "search",
                "job",
                "rmk",
                "success",
            )
        ):
            print(
                f"[{prefix}] "
                f"SCRIPT={script}"
            )


def probe_capgemini() -> None:
    _probe_rmk(
        prefix="CAPGEMINI-PROBE",
        base_url=(
            "https://careers."
            "capgemini.com"
        ),
    )


def probe_ltm() -> None:
    prefix = "LTM-PROBE"

    # Check the old hostname explicitly so we know the
    # canonical relationship rather than assuming it.
    old = _get(
        "https://careers."
        "ltimindtree.com"
    )

    _summary(
        prefix,
        "old-host",
        old,
    )

    print(
        f"[{prefix}] "
        f"old_host_final="
        f"{old.url}"
    )

    _probe_rmk(
        prefix=prefix,
        base_url=(
            "https://careers.ltm.com"
        ),
    )


# ============================================================
# CLEVERTAP / KULA
# ============================================================


def probe_clevertap() -> None:
    prefix = "CLEVERTAP-PROBE"

    print()
    print(
        f"[{prefix}] START"
    )

    board_url = (
        "https://careers.kula.ai/"
        "clevertap"
    )

    response = _get(
        board_url
    )

    _summary(
        prefix,
        "board",
        response,
    )

    if _blocked(
        prefix,
        "board",
        response,
    ):
        return

    if response.status_code != 200:
        print(
            f"[{prefix}] "
            f"body="
            f"{response.text[:3000]!r}"
        )
        return

    text = response.text

    markers = (
        "Senior Backend Engineer",
        "DevOps Engineer",
        "Mumbai",
        "job-posts",
        "job_posts",
        "job-boards",
        "api.kula.ai",
        "Bearer",
        "authorization",
        "token",
        "clevertap",
        "__NEXT_DATA__",
        "/api/",
        "graphql",
        "fetch(",
        "axios",
    )

    _contexts(
        prefix=prefix,
        source="board-html",
        text=text,
        markers=markers,
        max_hits=5,
        before=1800,
        after=4000,
    )

    links = _extract_links(
        response.url,
        text,
    )

    job_links = [
        link
        for link in links
        if (
            "careers.kula.ai/"
            "clevertap/" in link
            and link.rstrip("/")
            != board_url.rstrip("/")
        )
    ]

    print(
        f"[{prefix}] "
        f"links={len(links)} "
        f"candidate_job_links="
        f"{len(job_links)}"
    )

    for link in job_links[:30]:
        print(
            f"[{prefix}] "
            f"JOB_LINK={link}"
        )

    scripts = _extract_scripts(
        response.url,
        text,
    )

    print(
        f"[{prefix}] "
        f"scripts={len(scripts)}"
    )

    interesting_scripts: list[str] = []

    for script in scripts:
        lower = script.lower()

        if any(
            marker in lower
            for marker in (
                "_next",
                "main",
                "app",
                "chunk",
                "career",
                "job",
            )
        ):
            interesting_scripts.append(
                script
            )

    for script in interesting_scripts[
        :20
    ]:
        print(
            f"[{prefix}] "
            f"SCRIPT={script}"
        )

        try:
            script_response = _get(
                script
            )
        except requests.RequestException as exc:
            print(
                f"[{prefix}] "
                f"SCRIPT_FAILED "
                f"{type(exc).__name__}: "
                f"{exc}"
            )
            continue

        if (
            script_response.status_code
            != 200
        ):
            continue

        script_text = (
            script_response.text
        )

        lower = (
            script_text.lower()
        )

        hits = [
            marker
            for marker in markers
            if marker.lower()
            in lower
        ]

        if not hits:
            continue

        print(
            f"[{prefix}] "
            f"SCRIPT_MATCH "
            f"url={script} "
            f"hits={hits}"
        )

        _contexts(
            prefix=prefix,
            source=script,
            text=script_text,
            markers=(
                "api.kula.ai",
                "job-boards",
                "job-posts",
                "authorization",
                "bearer",
                "token",
                "clevertap",
            ),
            max_hits=6,
            before=3000,
            after=7000,
        )

        # Extract absolute API-looking URLs.
        urls = sorted(
            set(
                re.findall(
                    r'https?://'
                    r'[^"\'<>\s\\]+',
                    script_text,
                    flags=re.IGNORECASE,
                )
            )
        )

        for value in urls:
            if any(
                marker in value.lower()
                for marker in (
                    "kula.ai",
                    "/api/",
                    "job-board",
                    "job-post",
                )
            ):
                print(
                    f"[{prefix}] "
                    f"CANDIDATE_URL="
                    f"{value[:1500]!r}"
                )

    # --------------------------------------------------
    # Direct API test WITHOUT credentials.
    #
    # This is intentional. We want to know whether the
    # CleverTap public board has anonymous access despite
    # the generic Kula documentation requiring a token.
    # --------------------------------------------------

    api_url = (
        "https://api.kula.ai/v1/"
        "job-boards/job-posts"
    )

    api_response = requests.get(
        api_url,
        params={
            "page": 1,
            "limit": 100,
        },
        headers={
            **_HEADERS,
            "Accept":
                "application/json",
        },
        timeout=_TIMEOUT,
    )

    _summary(
        prefix,
        "anonymous-kula-api",
        api_response,
    )

    print(
        f"[{prefix}] "
        f"anonymous_api_body="
        f"{api_response.text[:5000]!r}"
    )

    # If HTML exposed at least one public job detail,
    # inspect it as a fallback source.
    if job_links:
        detail = _get(
            job_links[0]
        )

        _summary(
            prefix,
            "job-detail",
            detail,
        )

        if (
            detail.status_code
            == 200
        ):
            _contexts(
                prefix=prefix,
                source="job-detail",
                text=detail.text,
                markers=(
                    "Mumbai",
                    "location",
                    "department",
                    "employment",
                    "job",
                    "__NEXT_DATA__",
                    "application/ld+json",
                ),
                max_hits=4,
            )


# ============================================================
# MAIN
# ============================================================


def _run(
    name: str,
    function,
) -> None:
    print()
    print(
        "=" * 76
    )
    print(
        f"[BATCH-PROBE] {name}"
    )
    print(
        "=" * 76
    )

    try:
        function()

    except requests.RequestException as exc:
        print(
            f"[BATCH-PROBE] "
            f"{name}: REQUEST_FAILED "
            f"{type(exc).__name__}: "
            f"{exc}"
        )

    except Exception as exc:
        # One company's discovery failure must not prevent
        # evidence collection for the rest of the batch.
        print(
            f"[BATCH-PROBE] "
            f"{name}: FAILED "
            f"{type(exc).__name__}: "
            f"{exc}"
        )


def main() -> None:
    print(
        "[BATCH-PROBE] "
        "Starting company batch"
    )

    _run(
        "Deutsche Bank",
        probe_deutsche_bank,
    )

    _run(
        "TIAA",
        probe_tiaa,
    )

    _run(
        "Capgemini",
        probe_capgemini,
    )

    _run(
        "LTIMindtree / LTM",
        probe_ltm,
    )

    _run(
        "CleverTap",
        probe_clevertap,
    )

    print()
    print(
        "[BATCH-PROBE] Finished"
    )


if __name__ == "__main__":
    main()