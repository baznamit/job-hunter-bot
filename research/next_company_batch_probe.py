from __future__ import annotations

import html
import json
import re
from typing import Any
from urllib.parse import urljoin

import requests


_TIMEOUT = 30
_MAX_SCRIPT_BYTES = 6_000_000
_MAX_SCRIPTS = 30

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


def _clean(value: Any) -> str:
    if value is None:
        return ""

    return re.sub(
        r"\s+",
        " ",
        html.unescape(str(value)),
    ).strip()


def _get(
    url: str,
    *,
    params: dict | None = None,
    headers: dict | None = None,
) -> requests.Response:
    merged_headers = {
        **_HEADERS,
        "Accept": "*/*",
    }

    if headers:
        merged_headers.update(headers)

    return requests.get(
        url,
        params=params,
        headers=merged_headers,
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
    content_type = str(
        response.headers.get("Content-Type")
        or ""
    ).lower()

    preview = ""

    if (
        "text" in content_type
        or "html" in content_type
    ):
        preview = response.text[
            :5000
        ].lower()

    final_url = str(
        response.url or ""
    ).lower()

    server = str(
        response.headers.get("Server")
        or ""
    ).lower()

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
        r'<a[^>]+href=["\']'
        r'([^"\']+)["\']',
        text,
        flags=re.IGNORECASE,
    ):
        href = html.unescape(
            href
        ).strip()

        if not href:
            continue

        if href.lower().startswith(
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
    before: int = 1500,
    after: int = 3000,
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
                f"{_clean(context)[:5000]!r}"
            )

            start = (
                index
                + len(needle)
            )


def _target_location(
    value: str,
) -> bool:
    lower = value.lower()

    return any(
        term in lower
        for term in (
            "mumbai",
            "navi mumbai",
            "pune",
            "maharashtra",
            "bangalore",
            "bengaluru",
            "india",
        )
    )


# ============================================================
# SUCCESSFACTORS / RMK
# ============================================================


def _rmk_job_links(
    base_url: str,
    text: str,
) -> list[str]:
    result = []

    for link in _extract_links(
        base_url,
        text,
    ):
        lower = link.lower()

        if "/job/" not in lower:
            continue

        result.append(link)

    return result


def _inspect_rmk_page(
    *,
    prefix: str,
    label: str,
    response: requests.Response,
) -> None:
    text = response.text

    links = _extract_links(
        response.url,
        text,
    )

    pagination_links = [
        link
        for link in links
        if any(
            marker in link.lower()
            for marker in (
                "/search/",
                "startrow=",
                "page=",
                "offset=",
            )
        )
    ]

    print(
        f"[{prefix}] "
        f"{label} pagination_links="
        f"{len(pagination_links)}"
    )

    for link in pagination_links[:40]:
        print(
            f"[{prefix}] "
            f"{label} PAGE_LINK="
            f"{link}"
        )

    forms = re.findall(
        r"<form\b.*?</form>",
        text,
        flags=(
            re.IGNORECASE
            | re.DOTALL
        ),
    )

    print(
        f"[{prefix}] "
        f"{label} forms="
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
                "search",
                "keyword",
                "location",
                "job",
            )
        ):
            print(
                f"[{prefix}] "
                f"{label} FORM[{index}]="
                f"{cleaned[:6000]!r}"
            )

    inputs = re.findall(
        r"<input\b[^>]*>",
        text,
        flags=re.IGNORECASE,
    )

    for tag in inputs:
        lower = tag.lower()

        if any(
            marker in lower
            for marker in (
                "keyword",
                "location",
                "startrow",
                "search",
                "page",
            )
        ):
            print(
                f"[{prefix}] "
                f"{label} INPUT="
                f"{_clean(tag)!r}"
            )

    patterns = (
        r"[\d,]+\s+jobs",
        r"[\d,]+\s+results",
        (
            r"\d+\s*[-–]\s*\d+"
            r"\s+of\s+[\d,]+"
        ),
    )

    for pattern in patterns:
        matches = re.findall(
            pattern,
            text,
            flags=re.IGNORECASE,
        )

        if matches:
            print(
                f"[{prefix}] "
                f"{label} COUNT_TEXT="
                f"{[
                    _clean(value)
                    for value in matches[:20]
                ]}"
            )


def _probe_rmk_page(
    *,
    prefix: str,
    base_url: str,
    path: str,
) -> list[str]:
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
            "REQUEST_FAILED "
            f"{type(exc).__name__}: "
            f"{exc}"
        )

        return []

    _summary(
        prefix,
        path,
        response,
    )

    if _blocked(
        prefix,
        path,
        response,
    ):
        return []

    if response.status_code != 200:
        print(
            f"[{prefix}] "
            f"path={path!r} "
            f"body="
            f"{response.text[:2000]!r}"
        )

        return []

    links = _rmk_job_links(
        response.url,
        response.text,
    )

    print(
        f"[{prefix}] "
        f"path={path!r} "
        f"job_links={len(links)}"
    )

    for link in links[:20]:
        print(
            f"[{prefix}] "
            f"JOB_LINK={link}"
        )

    _inspect_rmk_page(
        prefix=prefix,
        label=path,
        response=response,
    )

    return links


def _probe_rmk_rss(
    *,
    prefix: str,
    base_url: str,
) -> None:
    url = (
        base_url.rstrip("/")
        + "/services/rss/job/"
    )

    try:
        response = _get(
            url,
            params={
                "keywords": "",
                "locale": "en_US",
            },
            headers={
                "Accept": (
                    "application/rss+xml,"
                    "application/xml,"
                    "text/xml;q=0.9,"
                    "*/*;q=0.8"
                ),
            },
        )
    except requests.RequestException as exc:
        print(
            f"[{prefix}] RSS "
            f"REQUEST_FAILED "
            f"{type(exc).__name__}: "
            f"{exc}"
        )
        return

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

    if response.status_code != 200:
        print(
            f"[{prefix}] "
            f"RSS_BODY="
            f"{response.text[:3000]!r}"
        )
        return

    text = response.text

    items = re.findall(
        r"<item\b.*?</item>",
        text,
        flags=(
            re.IGNORECASE
            | re.DOTALL
        ),
    )

    print(
        f"[{prefix}] "
        f"RSS_items={len(items)}"
    )

    for index, item in enumerate(
        items[:8]
    ):
        print(
            f"[{prefix}] "
            f"RSS_ITEM[{index}]="
            f"{_clean(item)[:5000]!r}"
        )

    target_items = [
        item
        for item in items
        if _target_location(
            _clean(item)
        )
    ]

    print(
        f"[{prefix}] "
        f"RSS_target_items="
        f"{len(target_items)}"
    )

    for index, item in enumerate(
        target_items[:20]
    ):
        print(
            f"[{prefix}] "
            f"RSS_TARGET[{index}]="
            f"{_clean(item)[:4000]!r}"
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

    try:
        home = _get(
            base_url
        )
    except requests.RequestException as exc:
        print(
            f"[{prefix}] "
            f"HOME_FAILED "
            f"{type(exc).__name__}: "
            f"{exc}"
        )
        return

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

    if home.status_code == 200:
        _contexts(
            prefix=prefix,
            source="home",
            text=home.text,
            markers=(
                "successfactors",
                "jobs2web",
                "rmk",
                "/search/",
                "/job/",
                "/services/rss/job/",
                "careerSiteCompany",
                "company=",
            ),
            max_hits=4,
        )

    candidates = (
        "search/",
        "search/0/",
        "search/25/",
        "search/50/",
        "search/100/",
    )

    results: dict[
        str,
        list[str],
    ] = {}

    for path in candidates:
        results[path] = (
            _probe_rmk_page(
                prefix=prefix,
                base_url=base_url,
                path=path,
            )
        )

    baseline = set(
        results.get(
            "search/",
            [],
        )
    )

    print(
        f"[{prefix}] "
        "PAGINATION_SUMMARY"
    )

    for path in candidates:
        current = set(
            results.get(
                path,
                [],
            )
        )

        print(
            f"[{prefix}] "
            f"path={path!r} "
            f"jobs={len(current)} "
            f"overlap_with_base="
            f"{len(baseline & current)} "
            f"different_from_base="
            f"{bool(current) and current != baseline}"
        )

    _probe_rmk_rss(
        prefix=prefix,
        base_url=base_url,
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

    print()
    print(
        f"[{prefix}] START"
    )

    # Informational only. Failure of the old hostname
    # must not prevent probing the current RMK site.
    try:
        old = _get(
            "https://careers."
            "ltimindtree.com"
        )

        _summary(
            prefix,
            "legacy-host",
            old,
        )

        print(
            f"[{prefix}] "
            f"legacy_final="
            f"{old.url}"
        )

    except requests.RequestException as exc:
        print(
            f"[{prefix}] "
            f"legacy_host_failed="
            f"{type(exc).__name__}: "
            f"{exc}"
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


def _inspect_embedded_json(
    *,
    prefix: str,
    text: str,
) -> None:
    blocks = re.findall(
        r'<script[^>]*'
        r'type=["\']'
        r'(?:application/json|'
        r'application/ld\+json)'
        r'["\'][^>]*>'
        r'(.*?)</script>',
        text,
        flags=(
            re.IGNORECASE
            | re.DOTALL
        ),
    )

    print(
        f"[{prefix}] "
        f"embedded_json_blocks="
        f"{len(blocks)}"
    )

    for index, block in enumerate(
        blocks[:20]
    ):
        print(
            f"[{prefix}] "
            f"EMBEDDED_JSON[{index}]="
            f"{_clean(block)[:10000]!r}"
        )

    next_data = re.search(
        r'<script[^>]+'
        r'id=["\']__NEXT_DATA__["\']'
        r'[^>]*>(.*?)</script>',
        text,
        flags=(
            re.IGNORECASE
            | re.DOTALL
        ),
    )

    if not next_data:
        return

    raw = next_data.group(1)

    print(
        f"[{prefix}] "
        f"NEXT_DATA="
        f"{_clean(raw)[:15000]!r}"
    )

    try:
        payload = json.loads(
            raw
        )

        if isinstance(
            payload,
            dict,
        ):
            print(
                f"[{prefix}] "
                f"NEXT_DATA_KEYS="
                f"{list(payload.keys())}"
            )

    except ValueError:
        print(
            f"[{prefix}] "
            "NEXT_DATA_NON_JSON"
        )


def _print_kula_urls(
    *,
    prefix: str,
    source: str,
    text: str,
) -> None:
    urls = sorted(
        set(
            re.findall(
                r'https?://'
                r'[^"\'<>\s\\]+',
                text,
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
                f"CANDIDATE_URL "
                f"source={source!r} "
                f"value="
                f"{value[:2000]!r}"
            )


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

    try:
        response = _get(
            board_url
        )
    except requests.RequestException as exc:
        print(
            f"[{prefix}] "
            f"BOARD_FAILED "
            f"{type(exc).__name__}: "
            f"{exc}"
        )
        return

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

    print(
        f"[{prefix}] "
        f"BOARD_PREVIEW="
        f"{_clean(response.text[:4000])!r}"
    )

    if response.status_code != 200:
        return

    text = response.text

    markers = (
        "clevertap",
        "Mumbai",
        "job-posts",
        "job_posts",
        "job-boards",
        "api.kula.ai",
        "authorization",
        "Bearer",
        "token",
        "accessToken",
        "access_token",
        "jobBoardToken",
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
        before=2000,
        after=5000,
    )

    _inspect_embedded_json(
        prefix=prefix,
        text=text,
    )

    _print_kula_urls(
        prefix=prefix,
        source="board-html",
        text=text,
    )

    links = _extract_links(
        response.url,
        text,
    )

    candidate_job_links = [
        link
        for link in links
        if (
            "careers.kula.ai/"
            "clevertap/" in link.lower()
            and link.rstrip("/")
            != board_url.rstrip("/")
        )
    ]

    print(
        f"[{prefix}] "
        f"links={len(links)} "
        f"candidate_job_links="
        f"{len(candidate_job_links)}"
    )

    for link in candidate_job_links[:30]:
        print(
            f"[{prefix}] "
            f"JOB_LINK={link}"
        )

    # ------------------------------------------------
    # Inspect frontend scripts for the actual board API.
    # ------------------------------------------------

    scripts = _extract_scripts(
        response.url,
        text,
    )

    print(
        f"[{prefix}] "
        f"scripts={len(scripts)}"
    )

    script_markers = (
        "api.kula.ai",
        "job-boards",
        "job-posts",
        "job_posts",
        "authorization",
        "bearer",
        "accessToken",
        "access_token",
        "jobBoardToken",
        "clevertap",
    )

    for script_url in scripts[
        :_MAX_SCRIPTS
    ]:
        print(
            f"[{prefix}] "
            f"SCRIPT={script_url}"
        )

        try:
            script_response = _get(
                script_url
            )
        except requests.RequestException as exc:
            print(
                f"[{prefix}] "
                f"SCRIPT_FAILED "
                f"url={script_url} "
                f"{type(exc).__name__}: "
                f"{exc}"
            )
            continue

        if (
            script_response.status_code
            != 200
        ):
            continue

        if (
            len(script_response.content)
            > _MAX_SCRIPT_BYTES
        ):
            print(
                f"[{prefix}] "
                f"SCRIPT_SKIPPED "
                f"url={script_url} "
                "reason=too_large"
            )
            continue

        script_text = (
            script_response.text
        )

        hits = [
            marker
            for marker in script_markers
            if marker.lower()
            in script_text.lower()
        ]

        if not hits:
            continue

        print(
            f"[{prefix}] "
            f"SCRIPT_MATCH "
            f"url={script_url} "
            f"hits={hits}"
        )

        _contexts(
            prefix=prefix,
            source=script_url,
            text=script_text,
            markers=script_markers,
            max_hits=8,
            before=4000,
            after=9000,
        )

        _print_kula_urls(
            prefix=prefix,
            source=script_url,
            text=script_text,
        )

    # ------------------------------------------------
    # Official Kula API without credentials.
    #
    # A 401/403 is useful evidence, so do NOT call
    # raise_for_status().
    # ------------------------------------------------

    official_api = (
        "https://api.kula.ai/v1/"
        "job-boards/job-posts"
    )

    try:
        api_response = _get(
            official_api,
            params={
                "page": 1,
                "limit": 100,
            },
            headers={
                "Accept":
                    "application/json",
            },
        )

        _summary(
            prefix,
            "anonymous-kula-api",
            api_response,
        )

        print(
            f"[{prefix}] "
            f"ANONYMOUS_API_BODY="
            f"{api_response.text[:6000]!r}"
        )

    except requests.RequestException as exc:
        print(
            f"[{prefix}] "
            f"ANONYMOUS_API_FAILED "
            f"{type(exc).__name__}: "
            f"{exc}"
        )

    # ------------------------------------------------
    # Public frontend endpoint candidates.
    #
    # These are discovery probes only. They are NOT
    # production assumptions.
    # ------------------------------------------------

    public_candidates = (
        (
            "careers-api-clevertap",
            (
                "https://careers.kula.ai/"
                "api/clevertap"
            ),
        ),
        (
            "careers-api-jobs",
            (
                "https://careers.kula.ai/"
                "api/clevertap/jobs"
            ),
        ),
    )

    for (
        label,
        candidate_url,
    ) in public_candidates:
        try:
            candidate = _get(
                candidate_url,
                headers={
                    "Accept":
                        "application/json",
                },
            )
        except requests.RequestException as exc:
            print(
                f"[{prefix}] "
                f"{label} FAILED "
                f"{type(exc).__name__}: "
                f"{exc}"
            )
            continue

        _summary(
            prefix,
            label,
            candidate,
        )

        print(
            f"[{prefix}] "
            f"{label}_BODY="
            f"{candidate.text[:6000]!r}"
        )

    # ------------------------------------------------
    # Inspect one public detail page if exposed.
    # ------------------------------------------------

    if candidate_job_links:
        detail_url = (
            candidate_job_links[0]
        )

        try:
            detail = _get(
                detail_url
            )
        except requests.RequestException as exc:
            print(
                f"[{prefix}] "
                f"DETAIL_FAILED "
                f"{type(exc).__name__}: "
                f"{exc}"
            )
            return

        _summary(
            prefix,
            "job-detail",
            detail,
        )

        if detail.status_code == 200:
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
                max_hits=5,
                before=1500,
                after=4000,
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
        print(
            f"[BATCH-PROBE] "
            f"{name}: FAILED "
            f"{type(exc).__name__}: "
            f"{exc}"
        )


def main() -> None:
    print(
        "[BATCH-PROBE] "
        "Starting unresolved company batch"
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