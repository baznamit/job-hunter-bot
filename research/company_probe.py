from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import Counter
import argparse
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse, urldefrag

import requests


TIMEOUT = (10, 25)
MAX_HTML_BYTES = 3_000_000
MAX_JS_BYTES = 5_000_000
MAX_JS_FILES = 4

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/127.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/json,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}

HCL_BASE = "https://careers.hcltech.com"
IBM_BASE = "https://www.ibm.com"

HCL_KNOWN_JOB_ID = "136528"


# ============================================================
# HTML PARSER
# ============================================================


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)

        self.links = []
        self.scripts = []
        self.forms = []
        self.embedded_scripts = []
        self._current_script = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)

        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])

        elif tag == "script":
            if attrs.get("src"):
                self.scripts.append(attrs["src"])
            else:
                self._current_script = {
                    "attrs": attrs,
                    "content": [],
                }

        elif tag == "form":
            self.forms.append({
                "action": attrs.get("action"),
                "method": attrs.get("method"),
            })

    def handle_data(self, data):
        if self._current_script is not None:
            self._current_script["content"].append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self._current_script is not None:
            script = self._current_script
            script["content"] = "".join(script["content"])

            self.embedded_scripts.append(script)
            self._current_script = None


# ============================================================
# COMMON HTTP
# ============================================================


def fetch(session, label, url, max_bytes=MAX_HTML_BYTES):
    try:
        with session.get(
            url,
            timeout=TIMEOUT,
            stream=True,
            allow_redirects=True,
        ) as response:

            chunks = []
            size = 0

            for chunk in response.iter_content(
                chunk_size=65536
            ):
                if not chunk:
                    continue

                size += len(chunk)

                if size > max_bytes:
                    print(
                        f"[{label}] TOO_LARGE "
                        f"limit={max_bytes}"
                    )
                    return None

                chunks.append(chunk)

            content = b"".join(chunks)

            content_type = response.headers.get(
                "Content-Type", ""
            )

            print(
                f"[{label}] "
                f"status={response.status_code} "
                f"final={response.url} "
                f"type={content_type!r} "
                f"bytes={size}"
            )

            if response.status_code != 200:
                print(
                    f"[{label}] "
                    f"ERROR_BODY={content[:160]!r}"
                )
                return None

            text = content.decode(
                response.encoding or "utf-8",
                errors="replace",
            )

            if any(
                marker in text[:4000].lower()
                for marker in (
                    "login.zscaler",
                    "access denied",
                    "captcha",
                )
            ):
                print(
                    f"[{label}] "
                    "SECURITY_OR_INTERSTITIAL"
                )
                return None

            return (
                response.url,
                content_type,
                text,
            )

    except requests.RequestException as exc:
        print(
            f"[{label}] "
            f"REQUEST_ERROR="
            f"{type(exc).__name__}: {exc}"
        )
        return None


def parse_page(result, label):
    if result is None:
        return None, [], []

    final_url, content_type, text = result

    if (
        "html" not in content_type.lower()
        or "<html" not in text[:2000].lower()
    ):
        print(f"[{label}] NOT_HTML")
        return None, [], []

    parser = PageParser()
    parser.feed(text)

    links = list(dict.fromkeys(
        urldefrag(urljoin(final_url, href))[0]
        for href in parser.links
        if not href.lower().startswith(
            ("javascript:", "mailto:", "tel:")
        )
    ))

    scripts = list(dict.fromkeys(
        urljoin(final_url, src)
        for src in parser.scripts
    ))

    print(
        f"[{label}] "
        f"links={len(links)} "
        f"scripts={len(scripts)} "
        f"forms={len(parser.forms)} "
        f"embedded_scripts={len(parser.embedded_scripts)}"
    )

    for script in parser.embedded_scripts:
        attrs = script["attrs"]

        if any(
            marker in str(attrs).lower()
            for marker in (
                "json",
                "next_data",
            )
        ):
            print(
                f"[{label}] "
                f"EMBEDDED_JSON "
                f"attrs={attrs} "
                f"bytes={len(script['content'])}"
            )

    return parser, links, scripts


# ============================================================
# HCLTECH
# ============================================================


def extract_hcl_jobs(links):
    jobs = {}

    for link in links:
        parsed = urlparse(link)

        if parsed.netloc.lower() != "careers.hcltech.com":
            continue

        match = re.search(
            r"/job/[^?#]+?/(\d+)-[a-z]{2}_[A-Z]{2}/?",
            link,
        )

        if match:
            jobs[match.group(1)] = link

    return jobs


def inspect_hcl_page(session, label, url):
    result = fetch(session, label, url)

    parser, links, scripts = parse_page(
        result,
        label,
    )

    jobs = extract_hcl_jobs(links)

    print(
        f"[{label}] "
        f"unique_jobs={len(jobs)} "
        f"known_job_present="
        f"{HCL_KNOWN_JOB_ID in jobs}"
    )

    for job_id, link in list(jobs.items())[:10]:
        print(
            f"[{label}] "
            f"JOB id={job_id} "
            f"url={link}"
        )

    pagination = [
        link
        for link in links
        if (
            urlparse(link).netloc.lower()
            == "careers.hcltech.com"
            and re.search(
                r"startrow|[?&]page=|/search/\d+",
                link,
                flags=re.IGNORECASE,
            )
        )
    ]

    for link in pagination[:15]:
        print(
            f"[{label}] "
            f"PAGINATION_CANDIDATE={link}"
        )

    if result is not None:
        text = result[2]

        for pattern in (
            r"Displaying\s+[^<]{0,100}",
            r"Showing\s+[^<]{0,100}",
            r"[\d,]+\s+(?:jobs|results)",
        ):
            matches = re.findall(
                pattern,
                text,
                flags=re.IGNORECASE,
            )

            if matches:
                print(
                    f"[{label}] "
                    f"RESULT_TEXT={matches[:5]}"
                )

    return jobs, pagination


def probe_hcltech(session):
    print()
    print("=" * 70)
    print("HCLTECH / SUCCESSFACTORS")
    print("=" * 70)

    sources = {
        "HCL-SEARCH": (
            HCL_BASE + "/search/"
        ),
        "HCL-INDIA": (
            HCL_BASE + "/go/India/9553955/"
        ),
        "HCL-NONTP": (
            HCL_BASE + "/go/NonTPDemand/9558355/"
        ),
    }

    inventory = {}
    navigation = {}

    for label, url in sources.items():
        jobs, pagination = inspect_hcl_page(
            session,
            label,
            url,
        )

        inventory[label] = jobs
        navigation[label] = pagination

    search_ids = set(
        inventory["HCL-SEARCH"]
    )

    india_ids = set(
        inventory["HCL-INDIA"]
    )

    nontp_ids = set(
        inventory["HCL-NONTP"]
    )

    print(
        "[HCL-COMPARE] "
        f"search={len(search_ids)} "
        f"india={len(india_ids)} "
        f"nontp={len(nontp_ids)}"
    )

    print(
        "[HCL-COMPARE] "
        f"india_search_overlap="
        f"{len(india_ids & search_ids)} "
        f"nontp_search_overlap="
        f"{len(nontp_ids & search_ids)} "
        f"india_nontp_overlap="
        f"{len(india_ids & nontp_ids)}"
    )

    # Follow only a discovered pagination link.
    for label in sources:
        candidates = navigation[label]

        if not candidates:
            continue

        target = candidates[0]

        next_jobs, _ = inspect_hcl_page(
            session,
            label + "-NEXT",
            target,
        )

        first_ids = set(inventory[label])
        next_ids = set(next_jobs)

        print(
            "[HCL-PAGINATION] "
            f"source={label} "
            f"next={target} "
            f"first_count={len(first_ids)} "
            f"next_count={len(next_ids)} "
            f"overlap={len(first_ids & next_ids)} "
            f"distinct={first_ids != next_ids}"
        )

        break

    else:
        print(
            "[HCL-PAGINATION] "
            "No discoverable pagination links"
        )

    detail_url = (
        HCL_BASE
        + "/job/Senior-Full-Stack-Developer/"
        + "136528-en_US/"
    )

    detail = fetch(
        session,
        "HCL-DETAIL",
        detail_url,
    )

    if detail is not None:
        _, links, _ = parse_page(
            detail,
            "HCL-DETAIL",
        )

        print(
            "[HCL-DETAIL] "
            f"known_id_present="
            f"{HCL_KNOWN_JOB_ID in detail[2]}"
        )

        for link in links:
            if "apply" in link.lower():
                print(
                    f"[HCL-DETAIL] "
                    f"APPLY_CANDIDATE={link}"
                )
                break

    rss = fetch(
        session,
        "HCL-RSS",
        HCL_BASE + "/services/rss/job/?locale=en_US",
    )

    if rss is not None:
        try:
            root = ET.fromstring(rss[2])
            items = root.findall(".//channel/item")

            print(
                "[HCL-RSS] "
                f"items={len(items)}"
            )

            job_ids = set()
            locations = Counter()

            for item in items:
                title = (
                    item.findtext("title") or ""
                ).strip()

                link = (
                    item.findtext("link") or ""
                ).strip()

                description = (
                    item.findtext("description") or ""
                ).strip()

                match = re.search(
                    r"/job/[^?#]+?/(\d+)-",
                    link,
                )

                if match:
                    job_ids.add(match.group(1))

                for city in (
                    "Mumbai",
                    "Navi Mumbai",
                    "Bangalore",
                    "Bengaluru",
                    "Pune",
                    "Hyderabad",
                ):
                    if city.lower() in (
                        title + " " + description
                    ).lower():
                        locations[city] += 1

            print(
                "[HCL-RSS] "
                f"unique_job_ids={len(job_ids)} "
                f"known_job_present="
                f"{HCL_KNOWN_JOB_ID in job_ids}"
            )

            print(
                "[HCL-RSS] "
                f"location_mentions={locations.most_common()}"
            )

            for item in items[:10]:
                print(
                    "[HCL-RSS] JOB "
                    f"title={item.findtext('title')!r} "
                    f"link={item.findtext('link')!r} "
                    f"date={item.findtext('pubDate')!r}"
                )

            channel = root.find("channel")

            if channel is not None:
                print(
                    "[HCL-RSS] "
                    f"channel_title={channel.findtext('title')!r}"
                )

        except ET.ParseError as exc:
            print(
                f"[HCL-RSS] XML_ERROR={exc}"
            )


# ============================================================
# IBM
# ============================================================


def extract_ibm_jobs(links):
    return list(dict.fromkeys(
        link
        for link in links
        if (
            urlparse(link).netloc.lower().endswith(
                "ibm.com"
            )
            and re.search(
                r"/careers/(?:job|jobs|search/job|job-details)",
                urlparse(link).path,
                flags=re.IGNORECASE,
            )
        )
    ))


def probe_ibm(session):
    print()
    print("=" * 70)
    print("IBM / BACKEND DISCOVERY")
    print("=" * 70)

    sources = {
        "IBM-SEARCH": (
            IBM_BASE + "/careers/search"
        ),
        "IBM-INDIA": (
            IBM_BASE
            + "/in-en/careers/search?"
            + "field_keyword_05%5B0%5D=India"
            + "&sort=dcdate_desc"
        ),
    }

    all_scripts = []

    for label, url in sources.items():
        result = fetch(
            session,
            label,
            url,
        )

        parser, links, scripts = parse_page(
            result,
            label,
        )

        all_scripts.extend(scripts)

        jobs = extract_ibm_jobs(links)

        print(
            f"[{label}] "
            f"candidate_job_links={len(jobs)}"
        )

        for link in jobs[:10]:
            print(
                f"[{label}] "
                f"JOB_CANDIDATE={link}"
            )

        pagination = [
            link
            for link in links
            if re.search(
                r"page=|offset=|start=|field_keyword",
                link,
                flags=re.IGNORECASE,
            )
        ]

        for link in pagination[:10]:
            print(
                f"[{label}] "
                f"NAV_CANDIDATE={link[:240]}"
            )

        if result is None:
            continue

        text = result[2]

        markers = (
            "__NEXT_DATA__",
            "drupalSettings",
            "application/ld+json",
            "JobPosting",
            "graphql",
            "algolia",
            "eightfold",
            "workday",
        )

        for marker in markers:
            print(
                f"[{label}] "
                f"marker={marker!r} "
                f"found={marker.lower() in text.lower()}"
            )

        if parser is not None:
            for form in parser.forms[:5]:
                print(
                    f"[{label}] "
                    f"FORM={form}"
                )

    # Inspect a bounded number of IBM-hosted JS assets.
    scored_scripts = sorted(
        set(all_scripts),
        key=lambda url: (
            -sum(
                marker in url.lower()
                for marker in (
                    "career",
                    "search",
                    "job",
                    "main",
                    "bundle",
                    "app",
                )
            ),
            url,
        ),
    )

    selected = [
        url
        for url in scored_scripts
        if urlparse(url).hostname in (
            "www.ibm.com",
            "ibm.com",
        )
    ][:MAX_JS_FILES]

    print(
        f"[IBM] selected_scripts="
        f"{len(selected)}"
    )

    for index, script_url in enumerate(
        selected,
        start=1,
    ):
        label = f"IBM-JS-{index}"

        result = fetch(
            session,
            label,
            script_url,
            max_bytes=MAX_JS_BYTES,
        )

        if result is None:
            continue

        _, content_type, text = result

        if (
            "html" in content_type.lower()
            or "<html" in text[:1000].lower()
        ):
            print(
                f"[{label}] "
                "HTML_NOT_JAVASCRIPT"
            )
            continue

        markers = (
            "graphql",
            "/api/",
            "jobs/search",
            "careers/search",
            "algolia",
            "workday",
            "eightfold",
            "fetch(",
            "axios",
        )

        for marker in markers:
            matches = list(
                re.finditer(
                    re.escape(marker),
                    text,
                    flags=re.IGNORECASE,
                )
            )

            if not matches:
                continue

            print(
                f"[{label}] "
                f"marker={marker!r} "
                f"hits={len(matches)}"
            )

            # Print only short, bounded context.
            # Review logs before sharing externally.
            for match in matches[:2]:
                snippet = text[
                    max(0, match.start() - 90):
                    match.end() + 150
                ]

                snippet = re.sub(
                    r"\s+",
                    " ",
                    snippet,
                )

                print(
                    f"[{label}] "
                    f"CONTEXT={snippet[:240]!r}"
                )

    print(
        "[IBM] If no jobs backend is identified, "
        "inspect one India-filtered search in "
        "Chrome DevTools > Network > Fetch/XHR."
    )


# ============================================================
# MAIN
# ============================================================


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--company",
        choices=("all", "ibm", "hcl"),
        default="all",
    )

    args = parser.parse_args()

    with requests.Session() as session:
        session.headers.update(HEADERS)

        if args.company in ("all", "hcl"):
            try:
                probe_hcltech(session)
            except Exception as exc:
                print(
                    "[HCL] PROBE_FAILED "
                    f"{type(exc).__name__}: {exc}"
                )

        if args.company in ("all", "ibm"):
            try:
                probe_ibm(session)
            except Exception as exc:
                print(
                    "[IBM] PROBE_FAILED "
                    f"{type(exc).__name__}: {exc}"
                )


if __name__ == "__main__":
    main()
