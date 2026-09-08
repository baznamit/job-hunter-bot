from __future__ import annotations

import html
import re
from urllib.parse import urljoin

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
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
}


# Network-oriented strings only.
#
# We intentionally do NOT search generic words such as
# "job", "position", or "location". Previous probes showed
# that those produce enormous amounts of CSS/library noise.
_NETWORK_MARKERS = (
    "fetch(",
    "axios",
    ".get(",
    ".post(",
    "xmlhttprequest",
    "/api/",
    "graphql",
    "searchjobs",
    "search-jobs",
    "embedjobs",
    "openings",
)


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


def _summary(
    company: str,
    label: str,
    response: requests.Response,
) -> None:
    print(
        f"[NETWORK-PROBE] {company}: "
        f"{label} "
        f"status={response.status_code} "
        f"final={response.url} "
        f"content_type="
        f"{response.headers.get('Content-Type')} "
        f"length={len(response.content)}"
    )


def _clean(
    value: str,
) -> str:
    return re.sub(
        r"\s+",
        " ",
        html.unescape(value),
    ).strip()


def _network_contexts(
    company: str,
    label: str,
    text: str,
) -> None:
    """
    Print small contexts around actual network-related
    expressions.

    Generic job/location strings are deliberately ignored.
    """

    lower = text.lower()

    for marker in _NETWORK_MARKERS:
        start = 0
        count = 0

        while count < 8:
            index = lower.find(
                marker.lower(),
                start,
            )

            if index < 0:
                break

            context = text[
                max(0, index - 700):
                index + 1800
            ]

            print(
                f"[NETWORK-PROBE] {company}: "
                f"{label} "
                f"marker={marker!r} "
                f"context="
                f"{_clean(context)[:2500]!r}"
            )

            start = (
                index
                + len(marker)
            )

            count += 1


def _absolute_urls(
    company: str,
    label: str,
    text: str,
) -> list[str]:
    urls: set[str] = set()

    patterns = (
        r'https?://[^"\'<>\s\\`]+',
        r'["\']('
        r'/[^"\']*'
        r'(?:api|graphql|job|career|search|opening)'
        r'[^"\']*'
        r')["\']',
    )

    for pattern in patterns:
        for match in re.findall(
            pattern,
            text,
            flags=re.IGNORECASE,
        ):
            if isinstance(
                match,
                tuple,
            ):
                match = match[0]

            value = html.unescape(
                match
            ).strip()

            value = value.rstrip(
                ".,);]}"
            )

            if not value:
                continue

            urls.add(value)

    result = sorted(urls)

    print(
        f"[NETWORK-PROBE] {company}: "
        f"{label} candidate_endpoints="
        f"{len(result)}"
    )

    for url in result[:60]:
        print(
            f"[NETWORK-PROBE] {company}: "
            f"{label} ENDPOINT={url[:2000]}"
        )

    return result


def _scripts(
    base_url: str,
    text: str,
) -> list[str]:
    result: list[str] = []

    for src in re.findall(
        r'<script[^>]+src=["\']([^"\']+)["\']',
        text,
        flags=re.IGNORECASE,
    ):
        src = html.unescape(
            src
        )

        if src.startswith(
            (
                "data:",
                "javascript:",
            )
        ):
            continue

        url = urljoin(
            base_url,
            src,
        )

        if url.startswith(
            (
                "http://",
                "https://",
            )
        ):
            result.append(url)

    return list(
        dict.fromkeys(result)
    )


def _probe_js(
    company: str,
    label: str,
    url: str,
) -> str | None:
    try:
        response = _get(url)

    except requests.RequestException as exc:
        print(
            f"[NETWORK-PROBE] {company}: "
            f"{label} FAILED "
            f"url={url} "
            f"error={type(exc).__name__}: {exc}"
        )
        return None

    _summary(
        company,
        label,
        response,
    )

    if response.status_code != 200:
        return None

    _network_contexts(
        company,
        label,
        response.text,
    )

    _absolute_urls(
        company,
        label,
        response.text,
    )

    return response.text


# =========================================================
# JUPITER / KEKA
# =========================================================

def probe_jupiter() -> None:
    """
    We already know the exact Keka widget JS.

    This probe's only purpose is to discover the HTTP
    request(s) that populate #khembedjobs.
    """

    company = "Jupiter"

    identifier = (
        "b5279857-cf81-4dde-a215-fc48957ee2b5"
    )

    widget_url = (
        "https://jupiter.keka.com/"
        "careers/api/embedjobs/js/"
        f"{identifier}"
    )

    print()
    print(
        "[NETWORK-PROBE] Jupiter: START"
    )

    text = _probe_js(
        company,
        "embedjobs-js",
        widget_url,
    )

    if not text:
        return

    # Specifically print function-call expressions which
    # are much more useful than generic API strings.
    call_patterns = (
        r'fetch\s*\([^)]{1,500}\)',
        r'axios\.[a-zA-Z]+\s*\([^)]{1,500}\)',
        r'\.get\s*\([^)]{1,500}\)',
        r'\.post\s*\([^)]{1,500}\)',
        r'open\s*\([^)]{1,500}\)',
    )

    calls: set[str] = set()

    for pattern in call_patterns:
        calls.update(
            re.findall(
                pattern,
                text,
                flags=re.IGNORECASE,
            )
        )

    print(
        "[NETWORK-PROBE] Jupiter: "
        f"network_calls={len(calls)}"
    )

    for call in sorted(calls)[:50]:
        print(
            "[NETWORK-PROBE] Jupiter: "
            f"CALL={_clean(call)[:2500]}"
        )


# =========================================================
# PHONEPE / GATSBY
# =========================================================

def _phonepe_chunk_url(
    runtime_text: str,
) -> str | None:
    """
    Resolve Gatsby chunk 4339 using the current runtime.

    From the previous run we know the current hash is:
        1f7467adb370882a0aba

    We still derive it dynamically so the probe survives a
    PhonePe deployment.
    """

    hash_match = re.search(
        r'4339\s*:\s*'
        r'["\']([a-f0-9]+)["\']',
        runtime_text,
        flags=re.IGNORECASE,
    )

    if not hash_match:
        return None

    chunk_hash = (
        hash_match.group(1)
    )

    print(
        "[NETWORK-PROBE] PhonePe: "
        f"chunk_4339_hash={chunk_hash}"
    )

    # Gatsby/Webpack commonly emits:
    #
    # component---src-pages-...-js-<hash>.js
    #
    # The runtime also tells us the logical chunk name.
    chunk_name_match = re.search(
        r'4339\s*:\s*'
        r'["\']'
        r'(component---src-pages-careers-'
        r'job-openings-index-js)'
        r'["\']',
        runtime_text,
        flags=re.IGNORECASE,
    )

    if not chunk_name_match:
        chunk_name = (
            "component---src-pages-careers-"
            "job-openings-index-js"
        )
    else:
        chunk_name = (
            chunk_name_match.group(1)
        )

    return (
        "https://www.phonepe.com/"
        "webstatic/14886/"
        f"{chunk_name}-{chunk_hash}.js"
    )


def probe_phonepe() -> None:
    company = "PhonePe"

    print()
    print(
        "[NETWORK-PROBE] PhonePe: START"
    )

    runtime_url = (
        "https://www.phonepe.com/"
        "webstatic/14886/"
        "webpack-runtime-"
        "12264017310890117f23.js"
    )

    try:
        runtime = _get(
            runtime_url
        )

    except requests.RequestException as exc:
        print(
            "[NETWORK-PROBE] PhonePe: "
            f"runtime FAILED "
            f"{type(exc).__name__}: {exc}"
        )
        return

    _summary(
        company,
        "webpack-runtime",
        runtime,
    )

    if runtime.status_code != 200:
        return

    chunk_url = _phonepe_chunk_url(
        runtime.text
    )

    if chunk_url:
        print(
            "[NETWORK-PROBE] PhonePe: "
            f"CHUNK_URL={chunk_url}"
        )

        chunk_text = _probe_js(
            company,
            "job-openings-chunk",
            chunk_url,
        )

        if chunk_text:
            return

    # If Gatsby's generated filename differs from our
    # expected construction, print the runtime function
    # responsible for constructing JS filenames.
    lower = runtime.text.lower()

    for marker in (
        ".u=",
        ".u =",
        "scriptfilename",
        "4339",
    ):
        index = lower.find(
            marker.lower()
        )

        if index < 0:
            continue

        context = runtime.text[
            max(
                0,
                index - 1500,
            ):
            index + 4000
        ]

        print(
            "[NETWORK-PROBE] PhonePe: "
            f"RUNTIME_CONTEXT marker={marker!r} "
            f"text={_clean(context)[:5500]!r}"
        )


# =========================================================
# ATLASSIAN
# =========================================================

def probe_atlassian() -> None:
    company = "Atlassian"

    print()
    print(
        "[NETWORK-PROBE] Atlassian: START"
    )

    page_url = (
        "https://www.atlassian.com/"
        "company/careers/all-jobs"
    )

    try:
        response = _get(
            page_url
        )

    except requests.RequestException as exc:
        print(
            "[NETWORK-PROBE] Atlassian: "
            f"page FAILED "
            f"{type(exc).__name__}: {exc}"
        )
        return

    _summary(
        company,
        "all-jobs",
        response,
    )

    if response.status_code != 200:
        return

    scripts = _scripts(
        response.url,
        response.text,
    )

    print(
        "[NETWORK-PROBE] Atlassian: "
        f"scripts={len(scripts)}"
    )

    # Prioritize the known main bundle and anything whose
    # filename explicitly references jobs/careers.
    scripts.sort(
        key=lambda url: (
            not any(
                value in url.lower()
                for value in (
                    "career",
                    "job",
                    "main.js",
                )
            ),
            url,
        )
    )

    for index, url in enumerate(
        scripts[:6]
    ):
        try:
            script = _get(
                url
            )

        except requests.RequestException:
            continue

        _summary(
            company,
            f"script-{index}",
            script,
        )

        if script.status_code != 200:
            continue

        text = script.text

        # Only inspect bundles that actually know about
        # career components.
        if not any(
            marker.lower()
            in text.lower()
            for marker in (
                "JobPostingDetails",
                "all-jobs",
                "jobposting",
                "careers",
            )
        ):
            continue

        for marker in (
            "JobPostingDetails",
            "jobposting",
            "all-jobs",
        ):
            lower = text.lower()
            start = 0

            for _ in range(8):
                pos = lower.find(
                    marker.lower(),
                    start,
                )

                if pos < 0:
                    break

                context = text[
                    max(0, pos - 2500):
                    pos + 6000
                ]

                print(
                    "[NETWORK-PROBE] Atlassian: "
                    f"COMPONENT marker={marker!r} "
                    f"context="
                    f"{_clean(context)[:8500]!r}"
                )

                start = (
                    pos
                    + len(marker)
                )

        _network_contexts(
            company,
            f"career-script-{index}",
            text,
        )

        _absolute_urls(
            company,
            f"career-script-{index}",
            text,
        )


# =========================================================
# MICROSOFT / EIGHTFOLD
# =========================================================

def probe_microsoft() -> None:
    """
    Do NOT probe /search again.

    The last run proved that /search redirects to Azure AD
    SAML. Instead inspect the anonymous /careers shell and
    its own JS for the backend/API it uses.
    """

    company = "Microsoft"

    print()
    print(
        "[NETWORK-PROBE] Microsoft: START"
    )

    page_url = (
        "https://apply.careers.microsoft.com/"
        "careers"
    )

    try:
        # First inspect redirect behavior explicitly.
        first = _get(
            page_url,
            allow_redirects=False,
        )

    except requests.RequestException as exc:
        print(
            "[NETWORK-PROBE] Microsoft: "
            f"careers FAILED "
            f"{type(exc).__name__}: {exc}"
        )
        return

    _summary(
        company,
        "careers-no-redirect",
        first,
    )

    if 300 <= first.status_code < 400:
        print(
            "[NETWORK-PROBE] Microsoft: "
            f"REDIRECT="
            f"{first.headers.get('Location')}"
        )

    try:
        response = _get(
            page_url
        )

    except requests.RequestException as exc:
        print(
            "[NETWORK-PROBE] Microsoft: "
            f"careers-follow FAILED "
            f"{type(exc).__name__}: {exc}"
        )
        return

    _summary(
        company,
        "careers",
        response,
    )

    # If /careers itself has now become authenticated,
    # stop. There is no point inspecting Azure AD JS.
    if (
        "login.microsoftonline.com"
        in response.url.lower()
    ):
        print(
            "[NETWORK-PROBE] Microsoft: "
            "CAREERS_AUTHENTICATED=true"
        )
        return

    if response.status_code != 200:
        return

    _network_contexts(
        company,
        "careers-html",
        response.text,
    )

    _absolute_urls(
        company,
        "careers-html",
        response.text,
    )

    scripts = _scripts(
        response.url,
        response.text,
    )

    print(
        "[NETWORK-PROBE] Microsoft: "
        f"scripts={len(scripts)}"
    )

    # Eightfold apps generally keep API/config logic in a
    # relatively small number of application bundles.
    scripts.sort(
        key=lambda url: (
            not any(
                value in url.lower()
                for value in (
                    "career",
                    "main",
                    "app",
                    "bundle",
                    "search",
                )
            ),
            url,
        )
    )

    for index, url in enumerate(
        scripts[:10]
    ):
        _probe_js(
            company,
            f"script-{index}",
            url,
        )


def main() -> None:
    print(
        "[NETWORK-PROBE] "
        "Starting final network-contract discovery"
    )

    probe_jupiter()
    probe_phonepe()
    probe_atlassian()
    probe_microsoft()

    print()
    print(
        "[NETWORK-PROBE] Finished"
    )


if __name__ == "__main__":
    main()