"""
Read-only S&P Global Workday/Jibe investigation.

Run:
    python -u -m research.spglobal_ats_probe
"""

import json
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from research.loader import load_registry
from src.providers.workday import WorkdayAdapter

TIMEOUT = 20
PUBLIC_LISTING = "https://careers.spglobal.com/jobs"
PUBLIC_DETAIL = (
    "https://careers.spglobal.com/jobs/324329?lang=en-us"
)


def inspect_workday(company):
    config = company.provider.config

    base = (
        f"https://{config.tenant}."
        f"{config.cluster}.myworkdayjobs.com"
    )
    board = config.board

    if not board:
        raise ValueError("S&P Global Workday board missing")

    endpoint = (
        f"{base}/wday/cxs/"
        f"{config.tenant}/{board}/jobs"
    )

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Origin": base,
        "Referer": f"{base}/en-US/{board}",
    }

    adapter = WorkdayAdapter()
    pages = {}

    print(f"[SPGLOBAL] workday_endpoint={endpoint}")

    for offset in (0, 20):
        try:
            data = adapter._request_page(
                url=endpoint,
                headers=headers,
                offset=offset,
                company=company,
            )

            postings = data.get("jobPostings") or []

            if not isinstance(postings, list):
                raise ValueError(
                    "Workday jobPostings is not a list"
                )

            ids = {
                str(item.get("externalPath"))
                for item in postings
                if isinstance(item, dict)
                and item.get("externalPath")
            }

            pages[offset] = ids

            print(
                f"[SPGLOBAL] workday_offset={offset} "
                f"total={data.get('total')!r} "
                f"count={len(postings)} "
                f"unique_paths={len(ids)}"
            )

            for item in postings[:5]:
                print(
                    "[SPGLOBAL] WORKDAY_SAMPLE "
                    f"title={item.get('title')!r} "
                    f"location={item.get('locationsText')!r} "
                    f"path={item.get('externalPath')!r}"
                )

        except (requests.RequestException, ValueError) as exc:
            print(
                f"[SPGLOBAL] workday_offset={offset} "
                f"ERROR={type(exc).__name__}: {exc}"
            )

    if 0 in pages and 20 in pages:
        print(
            "[SPGLOBAL] workday_page_overlap="
            f"{len(pages[0] & pages[20])}"
        )
        print(
            "[SPGLOBAL] workday_distinct_pages="
            f"{pages[0] != pages[20]}"
        )

    return pages


def inspect_public_page(label, url):
    print(f"\n[SPGLOBAL] inspecting={label}")

    try:
        response = requests.get(
            url,
            timeout=TIMEOUT,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "text/html",
            },
        )

        print(
            f"[SPGLOBAL] {label}_status="
            f"{response.status_code} "
            f"final={response.url} "
            f"content_type="
            f"{response.headers.get('Content-Type')!r} "
            f"bytes={len(response.content)}"
        )

        response.raise_for_status()

        if "html" not in response.headers.get(
            "Content-Type", ""
        ).lower():
            print(
                f"[SPGLOBAL] {label}: non-HTML response"
            )
            return

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        print(
            f"[SPGLOBAL] {label}_title="
            f"{soup.title.get_text(' ', strip=True) if soup.title else ''!r}"
        )

        links = []

        for anchor in soup.select("a[href]"):
            absolute = urljoin(
                response.url,
                anchor["href"],
            )

            parsed = urlparse(absolute)

            if (
                parsed.hostname == "careers.spglobal.com"
                and parsed.path.startswith("/jobs/")
                and parsed.path != "/jobs/"
            ):
                links.append(absolute)

        unique_links = list(dict.fromkeys(links))

        print(
            f"[SPGLOBAL] {label}_job_links="
            f"{len(unique_links)}"
        )

        for link in unique_links[:10]:
            print(f"[SPGLOBAL] JOB_LINK {link}")

        for script in soup.select(
            'script[type="application/ld+json"]'
        ):
            try:
                data = json.loads(
                    script.get_text()
                )
            except (ValueError, TypeError):
                continue

            objects = (
                data if isinstance(data, list)
                else [data]
            )

            for obj in objects:
                if not isinstance(obj, dict):
                    continue

                print(
                    f"[SPGLOBAL] {label}_JSONLD "
                    f"type={obj.get('@type')!r} "
                    f"title={obj.get('title')!r} "
                    f"identifier={obj.get('identifier')!r}"
                )

        scripts = [
            urljoin(response.url, tag["src"])
            for tag in soup.select("script[src]")
        ]

        jibe_scripts = [
            script
            for script in scripts
            if "jibe" in script.lower()
        ]

        print(
            f"[SPGLOBAL] {label}_jibe_scripts="
            f"{len(jibe_scripts)}"
        )

        for script in jibe_scripts[:5]:
            print(
                f"[SPGLOBAL] JIBE_SCRIPT {script}"
            )

        forms = soup.select("form")

        for form in forms[:5]:
            print(
                f"[SPGLOBAL] FORM "
                f"method={form.get('method', 'GET')!r} "
                f"action={urljoin(response.url, form.get('action', ''))!r}"
            )

    except requests.RequestException as exc:
        print(
            f"[SPGLOBAL] {label}_ERROR="
            f"{type(exc).__name__}: {exc}"
        )


def main():
    registry = load_registry()

    matches = [
        company
        for company in registry.companies
        if company.id == "spglobal"
    ]

    if len(matches) != 1:
        raise AssertionError(
            "Expected exactly one spglobal registry entry"
        )

    company = matches[0]

    print(
        f"[SPGLOBAL] company={company.name} "
        f"enabled={company.enabled} "
        f"provider={company.provider.type.value}"
    )

    if company.provider.type.value != "workday":
        raise AssertionError(
            "Unexpected S&P Global provider configuration"
        )

    inspect_workday(company)

    inspect_public_page(
        "jibe_listing",
        PUBLIC_LISTING,
    )

    inspect_public_page(
        "jibe_detail",
        PUBLIC_DETAIL,
    )

    print(
        "\n[SPGLOBAL] PROBE COMPLETE "
        "- no production state modified"
    )


if __name__ == "__main__":
    main()
