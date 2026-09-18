from __future__ import annotations

import html
import json
import re
from collections import Counter
from urllib.parse import urljoin, urlparse

import requests


_TIMEOUT = 30
_MAX_SCRIPT_BYTES = 6_000_000
_MAX_SCRIPTS_PER_SITE = 20

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/127.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
}


# ============================================================
# COMMON
# ============================================================


def _clean(value: str) -> str:
    return re.sub(
        r"\s+",
        " ",
        html.unescape(value),
    ).strip()


def _get(
    url: str,
    *,
    allow_redirects: bool = True,
) -> requests.Response:
    return requests.get(
        url,
        headers=_HEADERS,
        timeout=_TIMEOUT,
        allow_redirects=allow_redirects,
    )


def _response_summary(
    prefix: str,
    label: str,
    response: requests.Response,
) -> None:
    print(
        f"[{prefix}] {label}: "
        f"status={response.status_code} "
        f"final={response.url} "
        f"content_type="
        f"{response.headers.get('Content-Type')} "
        f"server={response.headers.get('Server')} "
        f"length={len(response.content)}"
    )


def _blocked_by_network(
    prefix: str,
    label: str,
    response: requests.Response,
) -> bool:
    """
    Detect when the requested careers/API URL was replaced by
    a corporate security/authentication page.

    This is especially useful when running the probe locally
    behind Zscaler. GitHub Actions should normally bypass this.
    """

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
        if "text" in content_type
        or "html" in content_type
        else ""
    )

    indicators = (
        "zscaler" in final_url,
        "zscaler" in server,
        "zscaler" in preview,
        "directory authentication" in preview,
        "smsamlq" in preview,
        "launch our security service" in preview,
    )

    if not any(indicators):
        return False

    print(
        f"[{prefix}] {label} "
        "BLOCKED_BY_NETWORK_SECURITY "
        f"final={response.url!r} "
        f"server="
        f"{response.headers.get('Server')!r}"
    )

    return True


def _contexts(
    *,
    prefix: str,
    source: str,
    text: str,
    markers: tuple[str, ...],
    max_hits: int = 4,
    before: int = 800,
    after: int = 1800,
) -> None:
    lower = text.lower()

    for marker in markers:
        needle = marker.lower()
        start = 0

        for _ in range(max_hits):
            index = lower.find(
                needle,
                start,
            )

            if index < 0:
                break

            context = text[
                max(0, index - before):
                index + after
            ]

            print(
                f"[{prefix}] CONTEXT "
                f"source={source} "
                f"marker={marker!r} "
                f"text="
                f"{_clean(context)[:2600]!r}"
            )

            start = index + len(
                needle
            )


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


def _extract_links(
    base_url: str,
    text: str,
) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    for href in re.findall(
        r'<a[^>]+href=["\']'
        r'([^"\']+)["\']',
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


def _url_strings(
    text: str,
) -> list[str]:
    """
    Extract absolute URLs and useful relative API-looking
    strings from HTML/JS without attempting to execute JS.
    """

    candidates: set[str] = set()

    for value in re.findall(
        r'https?://[^"\'<>\s\\]+',
        text,
        flags=re.IGNORECASE,
    ):
        candidates.add(
            html.unescape(value).rstrip(
                ".,);]}"
            )
        )

    for value in re.findall(
        r'["\']'
        r'([^"\']*(?:'
        r'/api/|/api\b|graphql|'
        r'jobs|job-search|search/jobs|'
        r'positions|openings|careers'
        r')[^"\']*)'
        r'["\']',
        text,
        flags=re.IGNORECASE,
    ):
        value = _clean(value)

        if (
            value
            and len(value) < 500
        ):
            candidates.add(
                value
            )

    return sorted(candidates)


def _print_interesting_urls(
    prefix: str,
    source: str,
    values: list[str],
) -> None:
    markers = (
        "/api/",
        "graphql",
        "job",
        "career",
        "search",
        "position",
        "opening",
        "phenom",
        "fynd",
        "wissen",
    )

    interesting = [
        value
        for value in values
        if any(
            marker in value.lower()
            for marker in markers
        )
    ]

    print(
        f"[{prefix}] {source}: "
        f"interesting_urls="
        f"{len(interesting)}"
    )

    for value in interesting[:80]:
        print(
            f"[{prefix}] URL "
            f"source={source} "
            f"value={value!r}"
        )


def _inspect_scripts(
    *,
    prefix: str,
    page_url: str,
    html_text: str,
    markers: tuple[str, ...],
) -> None:
    scripts = _extract_scripts(
        page_url,
        html_text,
    )

    print(
        f"[{prefix}] scripts="
        f"{len(scripts)}"
    )

    for url in scripts:
        print(
            f"[{prefix}] SCRIPT={url}"
        )

    scored: list[
        tuple[int, str]
    ] = []

    for url in scripts:
        lower = url.lower()

        score = sum(
            1
            for marker in (
                "main",
                "app",
                "bundle",
                "chunk",
                "career",
                "job",
                "search",
                "runtime",
                "static",
            )
            if marker in lower
        )

        scored.append(
            (score, url)
        )

    scored.sort(
        key=lambda item: (
            -item[0],
            item[1],
        )
    )

    inspected = 0

    for _, script_url in scored:
        if (
            inspected
            >= _MAX_SCRIPTS_PER_SITE
        ):
            break

        try:
            response = _get(
                script_url
            )
        except requests.RequestException as exc:
            print(
                f"[{prefix}] SCRIPT_FAILED "
                f"url={script_url} "
                f"error="
                f"{type(exc).__name__}: "
                f"{exc}"
            )
            continue

        _response_summary(
            prefix,
            "script",
            response,
        )

        if response.status_code != 200:
            continue

        if (
            len(response.content)
            > _MAX_SCRIPT_BYTES
        ):
            print(
                f"[{prefix}] SCRIPT_SKIPPED "
                f"reason=too_large "
                f"url={script_url}"
            )
            continue

        text = response.text
        lower = text.lower()

        hits = [
            marker
            for marker in markers
            if marker.lower() in lower
        ]

        if not hits:
            continue

        inspected += 1

        print(
            f"[{prefix}] SCRIPT_MATCH "
            f"url={script_url} "
            f"markers={hits}"
        )

        _contexts(
            prefix=prefix,
            source=script_url,
            text=text,
            markers=markers,
        )

        _print_interesting_urls(
            prefix,
            script_url,
            _url_strings(text),
        )


# ============================================================
# SYNECHRON — WORKDAY
# ============================================================


def _workday_page(
    *,
    tenant: str,
    cluster: str,
    board: str,
    offset: int,
) -> tuple[
    requests.Response,
    dict | None,
]:
    base = (
        f"https://{tenant}."
        f"{cluster}.myworkdayjobs.com"
    )

    endpoint = (
        f"{base}/wday/cxs/"
        f"{tenant}/{board}/jobs"
    )

    response = requests.post(
        endpoint,
        json={
            "appliedFacets": {},
            "limit": 20,
            "offset": offset,
            "searchText": "",
        },
        headers={
            "Content-Type":
                "application/json",
            "Accept":
                "application/json",
            "Origin":
                base,
            "Referer":
                f"{base}/en-US/{board}",
            "User-Agent":
                _HEADERS["User-Agent"],
        },
        timeout=_TIMEOUT,
    )

    try:
        payload = response.json()
    except ValueError:
        payload = None

    return response, payload


def _workday_key(
    item: dict,
) -> str:
    return str(
        item.get("externalPath")
        or item.get("title")
        or ""
    )


def probe_synechron() -> None:
    prefix = "SYNECHRON-PROBE"

    print()
    print(
        f"[{prefix}] START"
    )

    pages: list[
        tuple[int, dict]
    ] = []

    for offset in (
        0,
        20,
    ):
        response, payload = (
            _workday_page(
                tenant="synechron",
                cluster="wd1",
                board=(
                    "SynechronCareers"
                ),
                offset=offset,
            )
        )

        _response_summary(
            prefix,
            f"offset-{offset}",
            response,
        )

        if not isinstance(
            payload,
            dict,
        ):
            print(
                f"[{prefix}] "
                f"offset={offset} "
                f"body="
                f"{response.text[:1200]!r}"
            )
            continue

        jobs = (
            payload.get(
                "jobPostings"
            )
            or []
        )

        print(
            f"[{prefix}] "
            f"offset={offset} "
            f"total={payload.get('total')} "
            f"jobs={len(jobs)}"
        )

        pages.append(
            (
                offset,
                payload,
            )
        )

        for item in jobs[:10]:
            print(
                f"[{prefix}] JOB "
                f"title="
                f"{item.get('title')!r} "
                f"location="
                f"{item.get('locationsText')!r} "
                f"posted="
                f"{item.get('postedOn')!r} "
                f"path="
                f"{item.get('externalPath')!r}"
            )

    if len(pages) == 2:
        first = {
            _workday_key(item)
            for item in (
                pages[0][1].get(
                    "jobPostings"
                )
                or []
            )
            if _workday_key(item)
        }

        second = {
            _workday_key(item)
            for item in (
                pages[1][1].get(
                    "jobPostings"
                )
                or []
            )
            if _workday_key(item)
        }

        print(
            f"[{prefix}] "
            f"pagination_overlap="
            f"{len(first & second)} "
            f"pages_different="
            f"{first != second}"
        )


# ============================================================
# NIUM — LEVER
# ============================================================


def probe_nium() -> None:
    prefix = "NIUM-PROBE"

    print()
    print(
        f"[{prefix}] START"
    )

    url = (
        "https://api.lever.co/"
        "v0/postings/nium"
        "?mode=json"
    )

    response = _get(
        url
    )

    _response_summary(
        prefix,
        "lever",
        response,
    )

    if _blocked_by_network(
        prefix,
        "lever",
        response,
    ):
        return

    if response.status_code != 200:
        print(
            f"[{prefix}] body="
            f"{response.text[:1500]!r}"
        )
        return

    try:
        jobs = response.json()
    except ValueError:
        print(
            f"[{prefix}] NON_JSON "
            f"body="
            f"{response.text[:1500]!r}"
        )
        return

    if not isinstance(
        jobs,
        list,
    ):
        print(
            f"[{prefix}] "
            f"unexpected_type="
            f"{type(jobs).__name__}"
        )
        return

    print(
        f"[{prefix}] jobs={len(jobs)}"
    )

    locations = Counter()

    maharashtra = []

    for item in jobs:
        categories = (
            item.get("categories")
            or {}
        )

        location = str(
            categories.get(
                "location"
            )
            or "Unknown"
        )

        locations[
            location
        ] += 1

        lower = (
            location.lower()
        )

        if any(
            term in lower
            for term in (
                "mumbai",
                "navi mumbai",
                "pune",
                "maharashtra",
            )
        ):
            maharashtra.append(
                item
            )

    print(
        f"[{prefix}] "
        f"maharashtra_jobs="
        f"{len(maharashtra)}"
    )

    print(
        f"[{prefix}] "
        f"top_locations="
        f"{locations.most_common(20)}"
    )

    for item in maharashtra[:30]:
        categories = (
            item.get("categories")
            or {}
        )

        print(
            f"[{prefix}] JOB "
            f"id={item.get('id')!r} "
            f"title={item.get('text')!r} "
            f"location="
            f"{categories.get('location')!r} "
            f"team="
            f"{categories.get('team')!r} "
            f"department="
            f"{categories.get('department')!r} "
            f"url="
            f"{item.get('hostedUrl')!r}"
        )


# ============================================================
# WISSEN TECHNOLOGY
# ============================================================


def probe_wissen() -> None:
    prefix = "WISSEN-PROBE"

    print()
    print(
        f"[{prefix}] START"
    )

    url = (
        "https://www.wissen.com/"
        "career/"
        "opportunities-wissen-technology"
    )

    response = _get(
        url
    )

    _response_summary(
        prefix,
        "career-page",
        response,
    )

    if _blocked_by_network(
        prefix,
        "career-page",
        response,
    ):
        return

    if response.status_code != 200:
        print(
            f"[{prefix}] body="
            f"{response.text[:1800]!r}"
        )
        return

    text = response.text

    markers = (
        "Java Developer",
        "Data Engineer",
        "Mumbai",
        "Pune",
        "job",
        "career",
        "opening",
        "opportunity",
        "apply",
        "application",
        "vacancy",
        "position",
        "api",
        "graphql",
        "fetch(",
        "axios",
        "__NEXT_DATA__",
        "__INITIAL_STATE__",
        "application/ld+json",
    )

    _contexts(
        prefix=prefix,
        source="html",
        text=text,
        markers=markers,
    )

    links = _extract_links(
        response.url,
        text,
    )

    relevant_links = [
        link
        for link in links
        if any(
            marker in link.lower()
            for marker in (
                "career",
                "job",
                "apply",
                "opportun",
            )
        )
    ]

    print(
        f"[{prefix}] "
        f"links={len(links)} "
        f"relevant_links="
        f"{len(relevant_links)}"
    )

    for link in relevant_links[:80]:
        print(
            f"[{prefix}] LINK={link}"
        )

    # Forms are important because Wissen may use a single
    # careers page with job IDs passed into an application
    # form rather than individual detail pages.
    forms = re.findall(
        r"<form\b.*?</form>",
        text,
        flags=(
            re.IGNORECASE
            | re.DOTALL
        ),
    )

    print(
        f"[{prefix}] forms="
        f"{len(forms)}"
    )

    for index, form in enumerate(
        forms[:20]
    ):
        cleaned = _clean(
            form
        )

        if any(
            marker in cleaned.lower()
            for marker in (
                "job",
                "career",
                "apply",
                "resume",
                "position",
            )
        ):
            print(
                f"[{prefix}] FORM "
                f"index={index} "
                f"text="
                f"{cleaned[:5000]!r}"
            )

    # Enumerate useful class/id names. This gives us stable
    # selector candidates without dumping the whole page.
    classes = Counter(
        value
        for attr in re.findall(
            r'class=["\']([^"\']+)["\']',
            text,
            flags=re.IGNORECASE,
        )
        for value in attr.split()
    )

    ids = re.findall(
        r'id=["\']([^"\']+)["\']',
        text,
        flags=re.IGNORECASE,
    )

    interesting_classes = [
        (
            name,
            count,
        )
        for name, count
        in classes.most_common()
        if any(
            marker in name.lower()
            for marker in (
                "job",
                "career",
                "open",
                "position",
                "apply",
                "accordion",
                "vacan",
            )
        )
    ]

    print(
        f"[{prefix}] "
        f"interesting_classes="
        f"{interesting_classes[:80]}"
    )

    print(
        f"[{prefix}] "
        f"interesting_ids="
        f"{[
            value for value in ids
            if any(
                marker in value.lower()
                for marker in (
                    'job',
                    'career',
                    'open',
                    'position',
                    'apply',
                )
            )
        ][:80]}"
    )

    # Embedded JSON.
    json_scripts = re.findall(
        r'<script[^>]*'
        r'type=["\']application/'
        r'(?:ld\+json|json)["\']'
        r'[^>]*>(.*?)</script>',
        text,
        flags=(
            re.IGNORECASE
            | re.DOTALL
        ),
    )

    print(
        f"[{prefix}] "
        f"embedded_json_blocks="
        f"{len(json_scripts)}"
    )

    for index, block in enumerate(
        json_scripts[:20]
    ):
        print(
            f"[{prefix}] JSON "
            f"index={index} "
            f"text="
            f"{_clean(block)[:5000]!r}"
        )

    _print_interesting_urls(
        prefix,
        "html",
        _url_strings(text),
    )

    _inspect_scripts(
        prefix=prefix,
        page_url=response.url,
        html_text=text,
        markers=(
            "wissen",
            "career",
            "job",
            "opening",
            "position",
            "apply",
            "/api/",
            "graphql",
            "fetch(",
            "axios",
        ),
    )


# ============================================================
# FYND
# ============================================================


def probe_fynd() -> None:
    prefix = "FYND-PROBE"

    print()
    print(
        f"[{prefix}] START"
    )

    url = (
        "https://hiring.fynd.com/"
        "careers/gofynd"
    )

    response = _get(
        url
    )

    _response_summary(
        prefix,
        "career-page",
        response,
    )

    if _blocked_by_network(
        prefix,
        "career-page",
        response,
    ):
        return

    print(
        f"[{prefix}] preview="
        f"{_clean(response.text[:2500])!r}"
    )

    if response.status_code != 200:
        return

    text = response.text

    markers = (
        "gofynd",
        "job",
        "jobs",
        "opening",
        "position",
        "career",
        "Mumbai",
        "/api/",
        "api/",
        "graphql",
        "fetch(",
        "axios",
        "XMLHttpRequest",
        "__NEXT_DATA__",
        "_next/",
        "apollo",
        "urql",
        "query ",
        "mutation ",
    )

    _contexts(
        prefix=prefix,
        source="html",
        text=text,
        markers=markers,
    )

    _print_interesting_urls(
        prefix,
        "html",
        _url_strings(text),
    )

    links = _extract_links(
        response.url,
        text,
    )

    print(
        f"[{prefix}] links="
        f"{len(links)}"
    )

    for link in links[:80]:
        if any(
            marker in link.lower()
            for marker in (
                "job",
                "career",
                "position",
                "opening",
                "gofynd",
            )
        ):
            print(
                f"[{prefix}] LINK={link}"
            )

    # Next.js applications frequently expose useful runtime
    # state directly in __NEXT_DATA__.
    next_data_match = re.search(
        r'<script[^>]+id=["\']'
        r'__NEXT_DATA__["\'][^>]*>'
        r'(.*?)</script>',
        text,
        flags=(
            re.IGNORECASE
            | re.DOTALL
        ),
    )

    if next_data_match:
        next_data = (
            next_data_match.group(1)
        )

        print(
            f"[{prefix}] NEXT_DATA="
            f"{_clean(next_data)[:10000]!r}"
        )

        try:
            parsed = json.loads(
                next_data
            )

            print(
                f"[{prefix}] "
                f"NEXT_DATA_KEYS="
                f"{list(parsed.keys())}"
            )
        except ValueError:
            pass

    _inspect_scripts(
        prefix=prefix,
        page_url=response.url,
        html_text=text,
        markers=markers,
    )


# ============================================================
# COGNIZANT / PHENOM
# ============================================================


def probe_cognizant() -> None:
    prefix = "COGNIZANT-PROBE"

    print()
    print(
        f"[{prefix}] START"
    )

    urls = (
        (
            "base",
            "https://careers."
            "cognizant.com/"
            "india-en/jobs/",
        ),
        (
            "page-2",
            "https://careers."
            "cognizant.com/"
            "india-en/jobs/"
            "?page=2",
        ),
        (
            "pagesize-50",
            "https://careers."
            "cognizant.com/"
            "india-en/jobs/"
            "?pagesize=50",
        ),
        (
            "pagesize-100",
            "https://careers."
            "cognizant.com/"
            "india-en/jobs/"
            "?pagesize=100",
        ),
        (
            "pagesize-100-page-2",
            "https://careers."
            "cognizant.com/"
            "india-en/jobs/"
            "?pagesize=100&page=2",
        ),
    )

    base_response = None

    for label, url in urls:
        response = _get(
            url
        )

        _response_summary(
            prefix,
            label,
            response,
        )

        if response.status_code != 200:
            print(
                f"[{prefix}] "
                f"{label}_body="
                f"{response.text[:1200]!r}"
            )
            continue

        if label == "base":
            base_response = response

        text = response.text

        # Capture result-count text and several job URLs so
        # we can see whether ?location=Mumbai truly changes
        # the inventory.
        result_patterns = (
            r'Displaying\s+[^<]{0,150}',
            r'[\d,]+\s+matching jobs',
            r'[\d,]+\s+jobs',
        )

        for pattern in result_patterns:
            matches = re.findall(
                pattern,
                text,
                flags=re.IGNORECASE,
            )

            if matches:
                print(
                    f"[{prefix}] "
                    f"{label} "
                    f"RESULT_TEXT="
                    f"{[
                        _clean(value)
                        for value
                        in matches[:10]
                    ]}"
                )

        job_card_ids = re.findall(
            r'<div[^>]+'
            r'class=["\'][^"\']*'
            r'card-job[^"\']*["\']'
            r'[^>]+data-id=["\']'
            r'([^"\']+)["\']',
            text,
            flags=re.IGNORECASE,
        )

        print(
            f"[{prefix}] "
            f"{label} "
            f"job_cards="
            f"{len(job_card_ids)} "
            f"unique_job_cards="
            f"{len(set(job_card_ids))}"
        )

        print(
            f"[{prefix}] "
            f"{label} "
            f"sample_ids="
            f"{job_card_ids[:10]}"
        )

        job_links = [
            link
            for link in _extract_links(
                response.url,
                text,
            )
            if re.search(
                r"/jobs/[^/?#]+/",
                link,
                flags=re.IGNORECASE,
            )
        ]

        print(
            f"[{prefix}] "
            f"{label} "
            f"job_links="
            f"{len(job_links)}"
        )

        for link in job_links[:15]:
            print(
                f"[{prefix}] "
                f"{label} JOB_LINK={link}"
            )

    rss_url = (
        "https://careers."
        "cognizant.com/"
        "india-en/jobs/xml/"
        "?rss=true"
    )

    rss_response = _get(
        rss_url
    )

    _response_summary(
        prefix,
        "rss",
        rss_response,
    )

    if not _blocked_by_network(
        prefix,
        "rss",
        rss_response,
    ):
        rss_text = (
            rss_response.text
        )

        item_count = len(
            re.findall(
                r"<item\b",
                rss_text,
                flags=re.IGNORECASE,
            )
        )

        entry_count = len(
            re.findall(
                r"<entry\b",
                rss_text,
                flags=re.IGNORECASE,
            )
        )

        print(
            f"[{prefix}] RSS "
            f"items={item_count} "
            f"entries={entry_count} "
            f"content_type="
            f"{rss_response.headers.get('Content-Type')!r}"
        )

        print(
            f"[{prefix}] RSS_PREVIEW="
            f"{_clean(rss_text[:4000])!r}"
        )

    if (
        base_response is None
    ):
        return

    text = base_response.text

    markers = (
        "phenom",
        "phenompeople",
        "phApp",
        "jobSearch",
        "job-search",
        "searchJobs",
        "search-jobs",
        "location",
        "facet",
        "filter",
        "pagination",
        "pageSize",
        "page_size",
        "offset",
        "from",
        "limit",
        "/api/",
        "api/",
        "graphql",
        "fetch(",
        "axios",
        "XMLHttpRequest",
        "jobs",
    )

    _contexts(
        prefix=prefix,
        source="html",
        text=text,
        markers=markers,
    )

    _print_interesting_urls(
        prefix,
        "html",
        _url_strings(text),
    )

    # Meta tags often contain Phenom tenant/domain config.
    meta_tags = re.findall(
        r"<meta\b[^>]*>",
        text,
        flags=re.IGNORECASE,
    )

    for tag in meta_tags:
        lower = tag.lower()

        if any(
            marker in lower
            for marker in (
                "phenom",
                "career",
                "job",
                "domain",
                "tenant",
                "site",
                "locale",
            )
        ):
            print(
                f"[{prefix}] META="
                f"{_clean(tag)!r}"
            )

    _inspect_scripts(
        prefix=prefix,
        page_url=base_response.url,
        html_text=text,
        markers=markers,
    )


def probe_wissen_zoho() -> None:
    prefix = "WISSEN-ZOHO"

    print()
    print(f"[{prefix}] START")

    url = (
        "https://wissen.zohorecruit.in/"
        "recruit/v2/public/Job_Openings"
    )

    response = requests.get(
        url,
        params={
            "pagename": "Careers",
            "source": "CareerSite",
        },
        headers={
            **_HEADERS,
            "Accept": "application/json",
        },
        timeout=_TIMEOUT,
    )

    _response_summary(
        prefix,
        "jobs",
        response,
    )

    if _blocked_by_network(
        prefix,
        "jobs",
        response,
    ):
        return

    print(
        f"[{prefix}] final_url="
        f"{response.url}"
    )

    if response.status_code != 200:
        print(
            f"[{prefix}] body="
            f"{response.text[:3000]!r}"
        )
        return

    try:
        payload = response.json()
    except ValueError:
        print(
            f"[{prefix}] NON_JSON "
            f"body={response.text[:5000]!r}"
        )
        return

    print(
        f"[{prefix}] root_type="
        f"{type(payload).__name__}"
    )

    if isinstance(payload, dict):
        print(
            f"[{prefix}] root_keys="
            f"{list(payload.keys())}"
        )

    data = (
        payload.get("data")
        if isinstance(payload, dict)
        else None
    )

    info = (
        payload.get("info")
        if isinstance(payload, dict)
        else None
    )

    print(
        f"[{prefix}] data_type="
        f"{type(data).__name__} "
        f"jobs="
        f"{len(data) if isinstance(data, list) else None}"
    )

    print(
        f"[{prefix}] info="
        f"{str(info)[:5000]!r}"
    )

    if not isinstance(data, list):
        print(
            f"[{prefix}] payload="
            f"{json.dumps(payload, default=str)[:10000]}"
        )
        return

    for index, item in enumerate(
        data[:30]
    ):
        print(
            f"[{prefix}] JOB[{index}] "
            f"keys={list(item.keys())}"
        )

        print(
            f"[{prefix}] JOB[{index}] "
            f"payload="
            f"{json.dumps(item, default=str)[:5000]}"
        )

    mumbai = []

    for item in data:
        blob = json.dumps(
            item,
            default=str,
        ).lower()

        if (
            "mumbai" in blob
            or "maharashtra" in blob
        ):
            mumbai.append(item)

    print(
        f"[{prefix}] "
        f"mumbai_candidates="
        f"{len(mumbai)}"
    )

    for item in mumbai[:30]:
        print(
            f"[{prefix}] MUMBAI="
            f"{json.dumps(item, default=str)[:5000]}"
        )


def probe_fynd_targeted() -> None:
    prefix = "FYND-TARGETED"

    print()
    print(f"[{prefix}] START")

    base_url = (
        "https://hiring.fynd.com"
    )

    page = _get(
        f"{base_url}/careers/gofynd"
    )

    _response_summary(
        prefix,
        "page",
        page,
    )

    if _blocked_by_network(
        prefix,
        "page",
        page,
    ):
        return

    if page.status_code != 200:
        return

    initial_scripts = _extract_scripts(
        page.url,
        page.text,
    )

    print(
        f"[{prefix}] "
        f"initial_scripts="
        f"{len(initial_scripts)}"
    )

    discovered_chunks: set[str] = set()

    main_markers = (
        "JobsForCandidateFilter",
        "JobsForInstant",
        "graphql",
        "ApolloClient",
        "HttpLink",
        "createHttpLink",
        "uri:",
        "Failed to fetch jobs",
        "Failed to search jobs",
    )

    for script_url in initial_scripts:
        response = _get(
            script_url
        )

        _response_summary(
            prefix,
            "initial-script",
            response,
        )

        if response.status_code != 200:
            continue

        text = response.text

        for chunk in re.findall(
            r'["\']'
            r'(assets/[^"\']+\.js)'
            r'["\']',
            text,
            flags=re.IGNORECASE,
        ):
            lower = chunk.lower()

            if any(
                marker in lower
                for marker in (
                    "graphql",
                    "job",
                    "candidate",
                    "public",
                    "career",
                )
            ):
                discovered_chunks.add(
                    urljoin(
                        f"{base_url}/",
                        chunk,
                    )
                )

        hits = [
            marker
            for marker in main_markers
            if marker.lower()
            in text.lower()
        ]

        if not hits:
            continue

        print(
            f"[{prefix}] MATCH "
            f"url={script_url} "
            f"hits={hits}"
        )

        _contexts(
            prefix=prefix,
            source=script_url,
            text=text,
                markers=main_markers,
                max_hits=4,
                before=3500,
                after=7000,
        )

    print(
        f"[{prefix}] "
        f"discovered_chunks="
        f"{len(discovered_chunks)}"
    )

    for chunk in sorted(
        discovered_chunks
    ):
        print(
            f"[{prefix}] "
            f"CHUNK={chunk}"
        )

    known_chunks = {
        (
            f"{base_url}/assets/"
            "graphql-BM6Ljzt6.js"
        ),
        (
            f"{base_url}/assets/"
            "route-src-pages-public-"
            "JobDetailPage-tsx-Bv-kMpQx.js"
        ),
        (
            f"{base_url}/assets/"
            "route-src-pages-"
            "JobsPage-tsx-BdGlv9d9.js"
        ),
    }

    candidate_chunks = (
        discovered_chunks
        | known_chunks
    )

    chunk_markers = (
        "JobsForCandidateFilter",
        "JobsForInstant",
        "GetJob",
        "GetJobs",
        "SearchJobs",
        "PublicJob",
        "JobDetail",
        "query ",
        "mutation ",
        "ApolloClient",
        "HttpLink",
        "createHttpLink",
        "uri:",
        "/graphql",
        "/api/",
        "organizationSlug",
        "organization",
        "slug",
        "career",
        "careers",
        "gofynd",
    )

    for chunk_url in sorted(
        candidate_chunks
    ):
        try:
            response = _get(
                chunk_url
            )
        except requests.RequestException as exc:
            print(
                f"[{prefix}] "
                f"CHUNK_FAILED "
                f"url={chunk_url} "
                f"error={type(exc).__name__}: "
                f"{exc}"
            )
            continue

        _response_summary(
            prefix,
            "chunk",
            response,
        )

        if response.status_code != 200:
            continue

        text = response.text

        hits = [
            marker
            for marker in chunk_markers
            if marker.lower()
            in text.lower()
        ]

        if not hits:
            continue

        print(
            f"[{prefix}] "
            f"CHUNK_MATCH "
            f"url={chunk_url} "
            f"hits={hits}"
        )

        _contexts(
            prefix=prefix,
            source=chunk_url,
            text=text,
            markers=chunk_markers,
            max_hits=6,
            before=4500,
            after=9000,
        )

        urls = sorted(
            set(
                re.findall(
                    r'https?://'
                    r'[^"\'\s<>\\]+',
                    text,
                    flags=re.IGNORECASE,
                )
            )
        )

        for value in urls:
            lower = value.lower()

            if any(
                marker in lower
                for marker in (
                    "graphql",
                    "api",
                    "hiring.fynd",
                    "fynd.engineering",
                )
            ):
                print(
                    f"[{prefix}] "
                    f"CANDIDATE_URL="
                    f"{value[:1500]!r}"
                )

        relative_paths = sorted(
            set(
                re.findall(
                    r'["\']'
                    r'('
                    r'/(?:api|graphql)'
                    r'/[^"\']*'
                    r'|/graphql'
                    r')'
                    r'["\']',
                    text,
                    flags=re.IGNORECASE,
                )
            )
        )

        for value in relative_paths:
            print(
                f"[{prefix}] "
                f"RELATIVE_ENDPOINT="
                f"{value!r}"
            )


def main() -> None:
    print(
        "[FINAL-BATCH-PROBE] START"
    )

    probe_wissen_zoho()
    probe_fynd_targeted()

    print(
        "[FINAL-BATCH-PROBE] FINISHED"
    )


if __name__ == "__main__":
    main()