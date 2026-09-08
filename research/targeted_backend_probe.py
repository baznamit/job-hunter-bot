import html
import json
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
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/json;q=0.9,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


_MARKERS = (
    "eightfold",
    "keka",
    "greenhouse",
    "lever",
    "ashby",
    "workday",
    "icims",
    "phenom",
    "smartrecruiters",
    "algolia",
    "graphql",
    "/api/",
    "jobapi",
    "jobsapi",
    "job-list",
    "joblist",
    "job-search",
    "search-jobs",
    "searchjobs",
    "job-openings",
    "__next_data__",
    "__next_f.push",
)


def _get(
    url: str,
    *,
    params: dict | None = None,
) -> requests.Response:
    return requests.get(
        url,
        params=params,
        headers=_HEADERS,
        timeout=_TIMEOUT,
        allow_redirects=True,
    )


def _response(
    name: str,
    label: str,
    response: requests.Response,
) -> None:
    print(
        f"[TARGET-PROBE] {name}: "
        f"{label} "
        f"status={response.status_code} "
        f"final={response.url} "
        f"content_type="
        f"{response.headers.get('Content-Type')} "
        f"server="
        f"{response.headers.get('Server')} "
        f"length={len(response.content)}"
    )


def _clean(
    value: str,
) -> str:
    value = html.unescape(value)

    return re.sub(
        r"\s+",
        " ",
        value,
    ).strip()


def _contexts(
    name: str,
    source: str,
    text: str,
) -> None:
    lower = text.lower()

    for marker in _MARKERS:
        start = 0
        found = 0

        while found < 3:
            index = lower.find(
                marker.lower(),
                start,
            )

            if index < 0:
                break

            context = text[
                max(0, index - 500):
                index + 1500
            ]

            print(
                f"[TARGET-PROBE] {name}: "
                f"CONTEXT source={source} "
                f"marker={marker!r} "
                f"text={_clean(context)[:2000]!r}"
            )

            start = index + len(marker)
            found += 1


def _urls(
    name: str,
    source: str,
    text: str,
) -> list[str]:
    result: set[str] = set()

    # href/src
    candidates = re.findall(
        r'(?:href|src)=["\']([^"\']+)["\']',
        text,
        flags=re.IGNORECASE,
    )

    # URLs stored in JS/config/hidden HTML.
    candidates.extend(
        re.findall(
            r'https?://[^"\'<>\s\\]+',
            text,
            flags=re.IGNORECASE,
        )
    )

    for candidate in candidates:
        candidate = html.unescape(
            candidate
        ).strip()

        if candidate.startswith(
            (
                "data:",
                "javascript:",
                "mailto:",
                "tel:",
                "#",
            )
        ):
            continue

        url = urljoin(
            source,
            candidate,
        )

        if not url.startswith(
            ("http://", "https://")
        ):
            continue

        lower = url.lower()

        if any(
            marker in lower
            for marker in (
                "career",
                "job",
                "api",
                "search",
                "eightfold",
                "keka",
                "lever",
                "graphql",
            )
        ):
            result.add(url)

    urls = sorted(result)

    print(
        f"[TARGET-PROBE] {name}: "
        f"candidate_urls={len(urls)}"
    )

    for url in urls[:50]:
        print(
            f"[TARGET-PROBE] {name}: "
            f"URL={url[:1500]}"
        )

    return urls


def _scripts(
    name: str,
    source: str,
    text: str,
) -> list[str]:
    scripts = []

    for src in re.findall(
        r'<script[^>]+src=["\']([^"\']+)["\']',
        text,
        flags=re.IGNORECASE,
    ):
        url = urljoin(
            source,
            html.unescape(src),
        )

        if url.startswith(
            ("http://", "https://")
        ):
            scripts.append(url)

    print(
        f"[TARGET-PROBE] {name}: "
        f"scripts={len(scripts)}"
    )

    return scripts


def _inspect_scripts(
    name: str,
    scripts: list[str],
) -> None:
    # Only inspect JS. Avoid the image/resource problem
    # from our previous generic probe.
    js_urls = [
        url
        for url in scripts
        if (
            ".js" in url.lower()
            or "javascript" in url.lower()
        )
    ]

    # Prefer scripts whose URL itself looks career/job
    # related.
    js_urls.sort(
        key=lambda url: (
            not any(
                marker in url.lower()
                for marker in (
                    "career",
                    "job",
                    "search",
                    "lever",
                    "keka",
                    "eightfold",
                )
            ),
            url,
        )
    )

    for url in js_urls[:8]:
        try:
            response = _get(url)

        except requests.RequestException as exc:
            print(
                f"[TARGET-PROBE] {name}: "
                f"SCRIPT_FAILED url={url} "
                f"error={type(exc).__name__}: {exc}"
            )
            continue

        _response(
            name,
            "SCRIPT",
            response,
        )

        if response.status_code == 200:
            _contexts(
                name,
                url,
                response.text,
            )

            _urls(
                name,
                url,
                response.text,
            )


def _probe_page(
    name: str,
    label: str,
    url: str,
) -> requests.Response | None:
    try:
        response = _get(url)

    except requests.RequestException as exc:
        print(
            f"[TARGET-PROBE] {name}: "
            f"{label} FAILED "
            f"{type(exc).__name__}: {exc}"
        )
        return None

    _response(
        name,
        label,
        response,
    )

    print(
        f"[TARGET-PROBE] {name}: "
        f"{label} preview="
        f"{_clean(response.text[:1000])!r}"
    )

    if response.status_code == 200:
        _contexts(
            name,
            response.url,
            response.text,
        )

        _urls(
            name,
            response.url,
            response.text,
        )

    return response


# ---------------------------------------------------------
# PHONEPE
# ---------------------------------------------------------

def probe_phonepe() -> None:
    name = "PhonePe"

    urls = (
        (
            "all-jobs",
            "https://www.phonepe.com/careers/job-openings/",
        ),
        (
            "engineering",
            "https://www.phonepe.com/careers/job-openings/"
            "?department=engineering",
        ),
        (
            "tech-infra",
            "https://www.phonepe.com/careers/job-openings/"
            "?department=tech_infra",
        ),
        (
            "data-science",
            "https://www.phonepe.com/careers/job-openings/"
            "?department=data_science",
        ),
    )

    for label, url in urls:
        response = _probe_page(
            name,
            label,
            url,
        )

        if (
            response is None
            or response.status_code != 200
        ):
            continue

        # Look for obvious job/detail links.
        job_links = sorted(
            set(
                re.findall(
                    r'href=["\']([^"\']*'
                    r'(?:job|opening)[^"\']*)["\']',
                    response.text,
                    flags=re.IGNORECASE,
                )
            )
        )

        print(
            f"[TARGET-PROBE] {name}: "
            f"{label} job_links="
            f"{len(job_links)}"
        )

        for href in job_links[:10]:
            print(
                f"[TARGET-PROBE] {name}: "
                f"JOB_LINK="
                f"{urljoin(response.url, html.unescape(href))}"
            )

        scripts = _scripts(
            name,
            response.url,
            response.text,
        )

        if label == "engineering":
            _inspect_scripts(
                name,
                scripts,
            )


# ---------------------------------------------------------
# ATLASSIAN
# ---------------------------------------------------------

def probe_atlassian() -> None:
    name = "Atlassian"

    urls = (
        (
            "all-jobs",
            "https://www.atlassian.com/"
            "company/careers/all-jobs",
        ),
        (
            "bengaluru",
            "https://www.atlassian.com/"
            "company/careers/all-jobs"
            "?team=&location=Bengaluru&search=",
        ),
        (
            "engineering",
            "https://www.atlassian.com/"
            "company/careers/all-jobs"
            "?team=Engineering&location=&search=",
        ),
    )

    for label, url in urls:
        response = _probe_page(
            name,
            label,
            url,
        )

        if (
            response is None
            or response.status_code != 200
        ):
            continue

        # Current page should tell us whether jobs are SSR
        # or loaded by JS.
        hrefs = re.findall(
            r'href=["\']([^"\']+)["\']',
            response.text,
            flags=re.IGNORECASE,
        )

        job_hrefs = sorted(
            {
                urljoin(
                    response.url,
                    html.unescape(href),
                )
                for href in hrefs
                if (
                    "/job" in href.lower()
                    or "/careers/" in href.lower()
                )
            }
        )

        print(
            f"[TARGET-PROBE] {name}: "
            f"{label} job_hrefs="
            f"{len(job_hrefs)}"
        )

        for href in job_hrefs[:15]:
            print(
                f"[TARGET-PROBE] {name}: "
                f"JOB_LINK={href}"
            )

        scripts = _scripts(
            name,
            response.url,
            response.text,
        )

        if label == "all-jobs":
            _inspect_scripts(
                name,
                scripts,
            )


# ---------------------------------------------------------
# MICROSOFT / EIGHTFOLD
# ---------------------------------------------------------

def probe_microsoft() -> None:
    name = "Microsoft"

    urls = (
        (
            "eightfold-root",
            "https://apply.careers.microsoft.com/careers",
        ),
        (
            "eightfold-search",
            "https://apply.careers.microsoft.com/"
            "careers?query=Software%20Engineer"
            "&location=India",
        ),
    )

    for label, url in urls:
        response = _probe_page(
            name,
            label,
            url,
        )

        if (
            response is None
            or response.status_code != 200
        ):
            continue

        scripts = _scripts(
            name,
            response.url,
            response.text,
        )

        _inspect_scripts(
            name,
            scripts,
        )

        # Eightfold pages often expose application/config
        # JSON inside script tags.
        json_blocks = re.findall(
            r'<script[^>]*type=["\']'
            r'application/json["\'][^>]*>'
            r'(.*?)</script>',
            response.text,
            flags=(
                re.IGNORECASE
                | re.DOTALL
            ),
        )

        print(
            f"[TARGET-PROBE] {name}: "
            f"json_blocks={len(json_blocks)}"
        )

        for block in json_blocks[:5]:
            cleaned = html.unescape(
                block
            ).strip()

            try:
                parsed = json.loads(
                    cleaned
                )

            except (json.JSONDecodeError, TypeError):
                continue

            preview = json.dumps(
                parsed,
                ensure_ascii=False,
            )[:3000]

            print(
                f"[TARGET-PROBE] {name}: "
                f"JSON={preview}"
            )


# ---------------------------------------------------------
# JUPITER / KEKA
# ---------------------------------------------------------

def probe_jupiter() -> None:
    name = "Jupiter"

    response = _probe_page(
        name,
        "keka-careers",
        "https://jupiter.keka.com/careers",
    )

    if (
        response is None
        or response.status_code != 200
    ):
        return

    scripts = _scripts(
        name,
        response.url,
        response.text,
    )

    _inspect_scripts(
        name,
        scripts,
    )

    hrefs = re.findall(
        r'href=["\']([^"\']+)["\']',
        response.text,
        flags=re.IGNORECASE,
    )

    job_links = sorted(
        {
            urljoin(
                response.url,
                html.unescape(href),
            )
            for href in hrefs
            if (
                "job" in href.lower()
                or "career" in href.lower()
            )
        }
    )

    print(
        f"[TARGET-PROBE] {name}: "
        f"job_links={len(job_links)}"
    )

    for url in job_links[:20]:
        print(
            f"[TARGET-PROBE] {name}: "
            f"JOB_LINK={url}"
        )


def main() -> None:
    print(
        "[TARGET-PROBE] Starting focused "
        "backend discovery"
    )

    probe_phonepe()
    probe_atlassian()
    probe_microsoft()
    probe_jupiter()

    print(
        "[TARGET-PROBE] Finished"
    )


if __name__ == "__main__":
    main()