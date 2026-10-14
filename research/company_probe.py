
from __future__ import annotations

import argparse
import json
import re
import xml.etree.ElementTree as ET

from collections import Counter
from html.parser import HTMLParser
from urllib.parse import (
    urljoin,
    urlparse,
    parse_qs,
    urldefrag,
)

import requests


# ============================================================
# CONFIGURATION
# ============================================================

TIMEOUT = (10, 30)

MAX_HTML_BYTES = 4_000_000
MAX_JS_BYTES = 7_000_000
MAX_JS_FILES = 8

HCL = "https://careers.hcltech.com"
IBM = "https://www.ibm.com"
IBM_CAREERS = "https://careers.ibm.com"

HCL_KNOWN_ID = "136528"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/127.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/json,"
        "application/xml,*/*"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

JOB_PATTERN = re.compile(
    r"/job/[^\"'<>\s?#]+?/(\d+)"
    r"(?:-[a-z]{2}_[A-Z]{2})?"
    r"(?:/|[?#]|$)",
    re.IGNORECASE,
)

URL_PATTERN = re.compile(
    r"https?://[^\s\"'<>\\]+",
    re.IGNORECASE,
)

API_MARKERS = (
    "graphql",
    "/api/",
    "searchjobs",
    "search-jobs",
    "jobsearch",
    "job-search",
    "jobposting",
    "requisitions",
    "careers/search",
    "careers.ibm.com",
    "eightfold",
    "workday",
    "algolia",
    "phenom",
    "fetch(",
    "axios",
)


# ============================================================
# HTML PARSER
# ============================================================

class PageParser(HTMLParser):

    def __init__(self):
        super().__init__(convert_charrefs=True)

        self.links = []
        self.scripts = []
        self.embedded = []
        self.forms = []

        self.current_script = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)

        if tag == "a":
            href = attrs.get("href")

            if href:
                self.links.append(href)

        elif tag == "script":
            src = attrs.get("src")

            if src:
                self.scripts.append(src)
            else:
                self.current_script = {
                    "attrs": attrs,
                    "parts": [],
                }

        elif tag == "form":
            self.forms.append({
                "action": attrs.get("action"),
                "method": attrs.get("method"),
            })

    def handle_data(self, data):
        if self.current_script is not None:
            self.current_script["parts"].append(
                data
            )

    def handle_endtag(self, tag):
        if (
            tag == "script"
            and self.current_script is not None
        ):
            script = self.current_script

            script["text"] = "".join(
                script.pop("parts")
            )

            self.embedded.append(script)

            self.current_script = None


# ============================================================
# COMMON HELPERS
# ============================================================

def clean(value, limit=350):
    value = re.sub(
        r"\s+",
        " ",
        str(value),
    ).strip()

    return value[:limit]


def fetch(
    session,
    label,
    url,
    max_bytes=MAX_HTML_BYTES,
):
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
                    f"[{label}] HTTP_ERROR "
                    f"status={response.status_code}"
                )
                return None

            body = b"".join(chunks)

            text = body.decode(
                response.encoding or "utf-8",
                errors="replace",
            )

            final_host = urlparse(
                response.url
            ).hostname or ""

            if (
                "zscaler" in final_host.lower()
                or "login.zscaler" in text[:4000].lower()
            ):
                print(
                    f"[{label}] "
                    "INTERCEPTED_BY_ZSCALER"
                )
                return None

            if any(
                marker in text[:3000].lower()
                for marker in (
                    "<title>access denied",
                    "captcha challenge",
                )
            ):
                print(
                    f"[{label}] "
                    "SECURITY_PAGE"
                )
                return None

            return {
                "url": response.url,
                "content_type": content_type,
                "text": text,
            }

    except requests.RequestException as exc:
        print(
            f"[{label}] ERROR "
            f"{type(exc).__name__}: {exc}"
        )
        return None


def parse_html(result, label):
    if result is None:
        return None, [], []

    text = result["text"]

    if (
        "html" not in result["content_type"].lower()
        and "<html" not in text[:1000].lower()
    ):
        print(
            f"[{label}] NOT_HTML"
        )
        return None, [], []

    parser = PageParser()
    parser.feed(text)

    links = list(dict.fromkeys(
        urldefrag(
            urljoin(result["url"], href)
        )[0]
        for href in parser.links
        if not href.lower().startswith(
            ("javascript:", "mailto:", "tel:", "#")
        )
    ))

    scripts = list(dict.fromkeys(
        urljoin(result["url"], src)
        for src in parser.scripts
    ))

    print(
        f"[{label}] "
        f"links={len(links)} "
        f"scripts={len(scripts)} "
        f"embedded={len(parser.embedded)} "
        f"forms={len(parser.forms)}"
    )

    return parser, links, scripts


def extract_job_ids(text):
    return set(
        match.group(1)
        for match in JOB_PATTERN.finditer(text)
    )


def extract_job_urls(text):
    urls = {}

    for match in re.finditer(
        r"""(?:https?://[^"'<>\\\s]+)?/job/[^"'<>\\\s]+""",
        text,
        flags=re.IGNORECASE,
    ):
        candidate = match.group(0)

        candidate = candidate.replace(
            "\\/",
            "/",
        )

        job_match = JOB_PATTERN.search(
            candidate
        )

        if job_match:
            urls[job_match.group(1)] = candidate

    return urls


def show_contexts(
    label,
    text,
    markers,
    max_hits=2,
):
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
            f"MARKER={marker!r} "
            f"count={len(matches)}"
        )

        for match in matches[:max_hits]:
            snippet = text[
                max(0, match.start() - 130):
                match.end() + 220
            ]

            print(
                f"[{label}] CONTEXT "
                f"{clean(snippet)!r}"
            )


# ============================================================
# HCLTECH — HTML / RMK
# ============================================================

def inspect_hcl_page(session, label, url):
    result = fetch(
        session,
        label,
        url,
    )

    parser, links, scripts = parse_html(
        result,
        label,
    )

    if result is None:
        return set(), []

    text = result["text"]

    link_ids = extract_job_ids(
        "\n".join(links)
    )

    html_ids = extract_job_ids(text)

    embedded_ids = set()

    if parser:
        for script in parser.embedded:
            embedded_ids.update(
                extract_job_ids(
                    script["text"]
                )
            )

    all_ids = (
        link_ids
        | html_ids
        | embedded_ids
    )

    print(
        f"[{label}] "
        f"link_ids={len(link_ids)} "
        f"html_ids={len(html_ids)} "
        f"embedded_ids={len(embedded_ids)} "
        f"union_ids={len(all_ids)}"
    )

    print(
        f"[{label}] "
        f"known_job_present="
        f"{HCL_KNOWN_ID in all_ids}"
    )

    for job_id in sorted(all_ids)[:12]:
        print(
            f"[{label}] JOB_ID={job_id}"
        )

    show_contexts(
        label,
        text,
        (
            "/job/",
            "jobTitle",
            "jobLocation",
            "searchResults",
            "startrow",
            "pagination",
            "resultList",
            "jobSearch",
            "J2W",
        ),
        max_hits=2,
    )

    pagination = []

    for link in links:
        parsed = urlparse(link)

        if parsed.hostname != "careers.hcltech.com":
            continue

        query = parse_qs(parsed.query)

        if (
            "startrow" in query
            or "page" in query
            or re.search(
                r"/search/\d+/?$",
                parsed.path,
            )
        ):
            pagination.append(link)

    pagination = list(dict.fromkeys(
        pagination
    ))

    for link in pagination[:12]:
        print(
            f"[{label}] PAGE_LINK={link}"
        )

    return all_ids, pagination


# ============================================================
# HCLTECH — RSS
# ============================================================

def probe_hcl_rss(session):
    print()
    print("========== HCL RSS ==========")

    url = (
        HCL
        + "/services/rss/job/?locale=en_US"
    )

    result = fetch(
        session,
        "HCL-RSS",
        url,
    )

    if result is None:
        return

    try:
        root = ET.fromstring(
            result["text"]
        )
    except ET.ParseError as exc:
        print(
            f"[HCL-RSS] XML_ERROR={exc}"
        )
        return

    channel = root.find("channel")

    if channel is None:
        print(
            "[HCL-RSS] NO_CHANNEL"
        )
        return

    items = channel.findall("item")

    print(
        f"[HCL-RSS] items={len(items)}"
    )

    print(
        "[HCL-RSS] "
        f"channel_title={channel.findtext('title')!r}"
    )

    print(
        "[HCL-RSS] "
        f"description={clean(channel.findtext('description') or '')!r}"
    )

    atom_links = channel.findall(
        "{http://www.w3.org/2005/Atom}link"
    )

    for atom in atom_links[:5]:
        print(
            f"[HCL-RSS] ATOM_LINK="
            f"{atom.attrib}"
        )

    job_ids = set()
    locations = Counter()
    dates = Counter()

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

        date = (
            item.findtext("pubDate") or ""
        ).strip()

        match = JOB_PATTERN.search(link)

        if match:
            job_ids.add(
                match.group(1)
            )

        if date:
            dates[date] += 1

        combined = (
            title + " " + description
        ).lower()

        for city in (
            "Mumbai",
            "Navi Mumbai",
            "Bangalore",
            "Bengaluru",
            "Pune",
            "Hyderabad",
        ):
            if city.lower() in combined:
                locations[city] += 1

    print(
        f"[HCL-RSS] "
        f"unique_job_ids={len(job_ids)} "
        f"known_job_present="
        f"{HCL_KNOWN_ID in job_ids}"
    )

    print(
        f"[HCL-RSS] "
        f"location_mentions={locations.most_common()}"
    )

    print(
        f"[HCL-RSS] "
        f"dates={dates.most_common(5)}"
    )

    for item in items[:8]:
        print(
            "[HCL-RSS] JOB "
            f"title={item.findtext('title')!r} "
            f"url={item.findtext('link')!r}"
        )

    if len(items) == 20:
        print(
            "[HCL-RSS] WARNING "
            "Exactly 20 items; inventory completeness "
            "NOT established."
        )


# ============================================================
# HCLTECH — MAIN
# ============================================================

def probe_hcltech(session):
    print()
    print("=" * 70)
    print("HCLTECH — SUCCESSFACTORS")
    print("=" * 70)

    sources = {
        "HCL-SEARCH": (
            HCL + "/search/"
        ),
        "HCL-INDIA": (
            HCL + "/go/India/9553955/"
        ),
        "HCL-NONTP": (
            HCL + "/go/NonTPDemand/9558355/"
        ),
    }

    inventories = {}
    navigation = {}

    for label, url in sources.items():
        ids, pages = inspect_hcl_page(
            session,
            label,
            url,
        )

        inventories[label] = ids
        navigation[label] = pages

    search = inventories["HCL-SEARCH"]
    india = inventories["HCL-INDIA"]
    nontp = inventories["HCL-NONTP"]

    print(
        "[HCL-COMPARE] "
        f"search={len(search)} "
        f"india={len(india)} "
        f"nontp={len(nontp)}"
    )

    print(
        "[HCL-COMPARE] "
        f"india_search_overlap={len(india & search)} "
        f"nontp_search_overlap={len(nontp & search)} "
        f"india_nontp_overlap={len(india & nontp)}"
    )

    # Follow a discovered page only.
    followed = False

    for label, pages in navigation.items():
        if not pages:
            continue

        target = pages[0]

        next_ids, _ = inspect_hcl_page(
            session,
            label + "-NEXT",
            target,
        )

        first_ids = inventories[label]

        print(
            "[HCL-PAGINATION] "
            f"source={label} "
            f"next={target} "
            f"first={len(first_ids)} "
            f"next_count={len(next_ids)} "
            f"overlap={len(first_ids & next_ids)} "
            f"distinct={first_ids != next_ids}"
        )

        followed = True
        break

    if not followed:
        print(
            "[HCL-PAGINATION] "
            "No explicit next-page link found."
        )

    # Known job detail.
    detail = fetch(
        session,
        "HCL-DETAIL",
        HCL
        + "/job/Senior-Full-Stack-Developer/"
        + "136528-en_US/",
    )

    if detail:
        print(
            "[HCL-DETAIL] "
            f"known_id_present="
            f"{HCL_KNOWN_ID in detail['text']}"
        )

    probe_hcl_rss(session)


# ============================================================
# IBM — NEXT.JS STATE
# ============================================================

def inspect_ibm_next_data(
    parser,
    label,
):
    if parser is None:
        return None

    for script in parser.embedded:
        attrs = script["attrs"]

        if attrs.get("id") != "__NEXT_DATA__":
            continue

        try:
            data = json.loads(
                script["text"]
            )
        except ValueError as exc:
            print(
                f"[{label}] NEXT_JSON_ERROR={exc}"
            )
            return None

        print(
            f"[{label}] "
            f"NEXT_KEYS={list(data.keys())}"
        )

        print(
            f"[{label}] "
            f"BUILD_ID={data.get('buildId')!r}"
        )

        print(
            f"[{label}] "
            f"PAGE={data.get('page')!r}"
        )

        props = data.get(
            "props", {}
        )

        if isinstance(props, dict):
            print(
                f"[{label}] "
                f"PROPS_KEYS={list(props.keys())}"
            )

            page_props = props.get(
                "pageProps", {}
            )

            if isinstance(page_props, dict):
                print(
                    f"[{label}] "
                    f"PAGE_PROPS_KEYS="
                    f"{list(page_props.keys())}"
                )

                for key, value in page_props.items():
                    if any(
                        marker in key.lower()
                        for marker in (
                            "job",
                            "search",
                            "career",
                            "config",
                            "endpoint",
                        )
                    ):
                        print(
                            f"[{label}] "
                            f"PROP={key} "
                            f"type={type(value).__name__} "
                            f"preview={clean(value, 180)!r}"
                        )

        return data

    print(
        f"[{label}] NEXT_DATA_NOT_FOUND"
    )

    return None


# ============================================================
# IBM — SCRIPT INSPECTION
# ============================================================

def inspect_ibm_scripts(
    session,
    scripts,
):
    print()
    print("========== IBM JAVASCRIPT ==========")

    scripts = list(dict.fromkeys(
        scripts
    ))

    next_scripts = [
        url
        for url in scripts
        if "/_next/static/" in url
    ]

    print(
        f"[IBM-JS] "
        f"total_scripts={len(scripts)} "
        f"next_scripts={len(next_scripts)}"
    )

    for url in next_scripts[:20]:
        print(
            f"[IBM-JS] NEXT_SCRIPT={url}"
        )

    # Prefer actual Next.js application assets.
    ranked = sorted(
        next_scripts,
        key=lambda url: (
            -sum(
                marker in url.lower()
                for marker in (
                    "pages",
                    "career",
                    "search",
                    "webpack",
                    "main",
                    "chunk",
                )
            ),
            url,
        ),
    )

    selected = ranked[:MAX_JS_FILES]

    if not selected:
        print(
            "[IBM-JS] No Next.js script assets "
            "found in initial HTML."
        )

    for index, url in enumerate(
        selected,
        start=1,
    ):
        label = f"IBM-JS-{index}"

        result = fetch(
            session,
            label,
            url,
            max_bytes=MAX_JS_BYTES,
        )

        if result is None:
            continue

        text = result["text"]

        content_type = result[
            "content_type"
        ].lower()

        if (
            "html" in content_type
            or "<html" in text[:1000].lower()
        ):
            print(
                f"[{label}] HTML_NOT_JS"
            )
            continue

        print(
            f"[{label}] "
            f"script_bytes={len(text)}"
        )

        show_contexts(
            label,
            text,
            API_MARKERS,
            max_hits=2,
        )

        urls = set(
            URL_PATTERN.findall(text)
        )

        relevant = [
            value
            for value in urls
            if any(
                marker in value.lower()
                for marker in (
                    "career",
                    "job",
                    "api",
                    "search",
                    "ibm",
                )
            )
        ]

        print(
            f"[{label}] "
            f"candidate_urls={len(relevant)}"
        )

        for value in sorted(relevant)[:12]:
            print(
                f"[{label}] "
                f"URL={clean(value, 220)!r}"
            )


# ============================================================
# IBM — MAIN
# ============================================================

def probe_ibm(session):
    print()
    print("=" * 70)
    print("IBM — CAREERS BACKEND")
    print("=" * 70)

    sources = {
        "IBM-SEARCH": (
            IBM + "/careers/search"
        ),
        "IBM-INDIA": (
            IBM
            + "/in-en/careers/search?"
            + "field_keyword_05%5B0%5D=India"
            + "&sort=dcdate_desc"
        ),
        "IBM-CAREERS": (
            IBM_CAREERS
            + "/en_US/careers/SearchJobs/"
        ),
    }

    all_scripts = []

    for label, url in sources.items():
        result = fetch(
            session,
            label,
            url,
        )

        if result is None:
            continue

        parser, links, scripts = parse_html(
            result,
            label,
        )

        all_scripts.extend(scripts)

        print(
            f"[{label}] "
            f"job_path_occurrences="
            f"{len(re.findall('/job/', result['text'], re.I))}"
        )

        show_contexts(
            label,
            result["text"],
            (
                "careers.ibm.com",
                "SearchJobs",
                "jobId",
                "requisition",
                "jobSearch",
                "api/",
                "graphql",
            ),
            max_hits=2,
        )

        if parser:
            inspect_ibm_next_data(
                parser,
                label,
            )

        job_links = [
            link
            for link in links
            if any(
                marker in link.lower()
                for marker in (
                    "/job/",
                    "/jobdetails/",
                    "jobid=",
                    "requisition",
                )
            )
        ]

        print(
            f"[{label}] "
            f"candidate_job_links={len(job_links)}"
        )

        for link in job_links[:10]:
            print(
                f"[{label}] JOB_LINK={link}"
            )

    inspect_ibm_scripts(
        session,
        all_scripts,
    )

    print(
        "[IBM] If no public job-results endpoint "
        "is identified, inspect one India-filtered "
        "search in browser DevTools Network."
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
            try:
                probe_hcltech(session)
            except Exception as exc:
                print(
                    "[HCL] FAILED "
                    f"{type(exc).__name__}: {exc}"
                )

        if args.company in ("all", "ibm"):
            try:
                probe_ibm(session)
            except Exception as exc:
                print(
                    "[IBM] FAILED "
                    f"{type(exc).__name__}: {exc}"
                )

    print()
    print("[BATCH-PROBE] Finished")


if __name__ == "__main__":
    main()
