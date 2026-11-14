
#!/usr/bin/env python3
"""
Combined public career-portal probe.

Targets:
- Wissen Technology
- Deloitte India
- Deloitte USI
- Mphasis
- S&P Global

Uses public HTTP GET requests only.
No authentication, CAPTCHA bypass, or hidden API guessing.

Run:
    python -u -m research.wissen_deloitte_mphasis_spglobal_probe
"""

import json
import re
import sys
import time
from collections import Counter
from html import unescape
from urllib.parse import (
    parse_qs,
    urldefrag,
    urljoin,
    urlparse,
)

import requests
from bs4 import BeautifulSoup


TIMEOUT = (8, 20)
MAX_BYTES = 2_000_000
DELAY_SECONDS = 0.5

HEADERS = {
    "User-Agent": (
        "JobHunterResearch/1.0 "
        "(public career portal integration validation)"
    ),
    "Accept": "text/html,application/json,application/xml;q=0.9,*/*;q=0.5",
}

TARGETS = [
    {
        "name": "WISSEN-LIST",
        "url": "https://careers.wissen.com/jobs/Careers",
    },
    {
        "name": "WISSEN-DETAIL",
        "url": (
            "https://careers.wissen.com/jobs/Careers/"
            "80238000218701421/Java-Full-Stack-Developer"
        ),
    },
    {
        "name": "WISSEN-ALT",
        "url": "https://jobs.wissen.com/",
    },
    {
        "name": "DELOITTE-INDIA-P0",
        "url": (
            "https://southasiacareers.deloitte.com/"
            "go/Deloitte-India/718244/?q=&title=Java"
        ),
    },
    {
        "name": "DELOITTE-INDIA-P25",
        "url": (
            "https://southasiacareers.deloitte.com/"
            "go/Deloitte-India/718244/25/?q=&title=Java"
        ),
    },
    {
        "name": "DELOITTE-INDIA-P50",
        "url": (
            "https://southasiacareers.deloitte.com/"
            "go/Deloitte-India/718244/50/?q=&title=Java"
        ),
    },
    {
        "name": "DELOITTE-INDIA-DETAIL",
        "url": (
            "https://southasiacareers.deloitte.com/job/"
            "Mumbai-Senior-Consultant-Java-Springboot-Backend-"
            "Mumbai-Engineering-Platform-Development-%26-Integrat/"
            "59689444/"
        ),
    },
    {
        "name": "DELOITTE-USI",
        "url": "https://usijobs.deloitte.com/",
    },
    {
        "name": "DELOITTE-USI-DETAIL",
        "url": (
            "https://usijobs.deloitte.com/en_US/careersUSI/"
            "JobDetail/USI-EH27-EA-MF-UK-Business-Operation-"
            "Support-Associate-Analyst/369345"
        ),
    },
    {
        "name": "MPHASIS-INDIA",
        "url": (
            "https://careers.mphasis.com/home/"
            "hot-jobs/location-search/india.html"
        ),
    },
    {
        "name": "MPHASIS-HOTJOBS",
        "url": "https://www2.mphasis.com/hot-jobs.html",
    },
    {
        "name": "SPGLOBAL-LIST",
        "url": "https://careers.spglobal.com/jobs",
    },
    {
        "name": "SPGLOBAL-DETAIL",
        "url": "https://careers.spglobal.com/jobs/324329?lang=en-us",
    },
]


def limited_get(session, url):
    started = time.perf_counter()

    with session.get(
        url,
        timeout=TIMEOUT,
        allow_redirects=True,
        stream=True,
    ) as response:
        chunks = []
        size = 0
        truncated = False

        for chunk in response.iter_content(chunk_size=65536):
            if not chunk:
                continue

            remaining = MAX_BYTES - size

            if len(chunk) > remaining:
                chunks.append(chunk[:remaining])
                size += remaining
                truncated = True
                break

            chunks.append(chunk)
            size += len(chunk)

            if size >= MAX_BYTES:
                truncated = True
                break

        body = b"".join(chunks)

        encoding = response.encoding or "utf-8"
        content = body.decode(encoding, errors="replace")

        return {
            "status": response.status_code,
            "url": response.url,
            "redirects": [
                r.status_code for r in response.history
            ],
            "type": response.headers.get("Content-Type", ""),
            "bytes": size,
            "truncated": truncated,
            "elapsed": round(
                time.perf_counter() - started, 2
            ),
            "content": content,
        }


def classify_page(result):
    text = result["content"].lower()
    final_host = urlparse(result["url"]).hostname or ""

    security_markers = (
        "zscalerthree.net",
        "access denied",
        "captcha",
        "verify you are human",
        "cloudflare challenge",
    )

    if (
        any(marker in text[:20000] for marker in security_markers)
        or "zscalerthree.net" in final_host
    ):
        return "SECURITY_OR_ACCESS_PAGE"

    if result["status"] in (401, 403, 429):
        return "ACCESS_RESTRICTED"

    if result["status"] >= 400:
        return "HTTP_ERROR"

    if "json" in result["type"].lower():
        return "JSON"

    if "html" in result["type"].lower():
        return "HTML"

    return "OTHER"


def inspect_html(content, base_url):
    soup = BeautifulSoup(content, "html.parser")

    links = []
    job_links = []
    scripts = []
    forms = []
    json_ld = []

    seen = set()

    for tag in soup.find_all("a", href=True):
        href = urljoin(base_url, tag["href"])
        parsed = urlparse(href)

        if parsed.scheme not in ("http", "https"):
            continue

        if href in seen:
            continue

        seen.add(href)
        links.append(href)

        path = parsed.path.lower()

        patterns = (
            "/job/",
            "/jobs/",
            "/jobdetail/",
            "/jobdesc",
            "/careers/",
        )

        if any(pattern in path for pattern in patterns):
            job_links.append(href)

    for tag in soup.find_all("script"):
        src = tag.get("src")

        if src:
            scripts.append(urljoin(base_url, src))

        if tag.get("type", "").lower() == "application/ld+json":
            try:
                json_ld.append(json.loads(tag.get_text()))
            except (ValueError, TypeError):
                pass

    for form in soup.find_all("form"):
        forms.append({
            "action": urljoin(
                base_url,
                form.get("action", ""),
            ),
            "method": form.get("method", "GET").upper(),
            "inputs": [
                {
                    "name": field.get("name"),
                    "type": field.get("type"),
                }
                for field in form.find_all(
                    ["input", "select"]
                )[:20]
            ],
        })

    text = soup.get_text(" ", strip=True)

    markers = (
        "__NEXT_DATA__",
        "__INITIAL_STATE__",
        "JobPosting",
        "jobSearchResult",
        "totalJobs",
        "graphql",
        "workday",
        "successfactors",
        "zoho",
        "pagination",
        "pageNumber",
        "requisition",
    )

    marker_counts = {
        marker: content.lower().count(marker.lower())
        for marker in markers
        if marker.lower() in content.lower()
    }

    return {
        "links": links,
        "job_links": job_links,
        "scripts": scripts,
        "forms": forms,
        "json_ld": json_ld,
        "markers": marker_counts,
        "title": (
            soup.title.get_text(" ", strip=True)
            if soup.title else ""
        ),
        "text_preview": text[:350],
    }


def extract_job_ids(urls):
    ids = set()

    for url in urls:
        path = urlparse(url).path

        for pattern in (
            r"/jobs/Careers/(\d+)",
            r"/jobs/careers/(\d+)",
            r"/jobs/(\d+)",
            r"/job/[^/]+/(\d+)",
            r"/JobDetail/[^/]+/(\d+)",
        ):
            match = re.search(
                pattern, path, flags=re.IGNORECASE
            )

            if match:
                ids.add(match.group(1))

    return ids


def print_result(name, result):
    print("\n" + "=" * 72)
    print(name)
    print("=" * 72)

    kind = classify_page(result)

    print(
        f"[{name}] status={result['status']} "
        f"type={result['type']!r} "
        f"bytes={result['bytes']} "
        f"elapsed={result['elapsed']}s"
    )

    print(f"[{name}] final={result['url']}")
    print(f"[{name}] redirects={result['redirects']}")
    print(f"[{name}] classification={kind}")
    print(f"[{name}] truncated={result['truncated']}")

    if kind == "JSON":
        try:
            data = json.loads(result["content"])

            if isinstance(data, dict):
                print(
                    f"[{name}] JSON_KEYS="
                    f"{list(data.keys())[:25]}"
                )
            elif isinstance(data, list):
                print(
                    f"[{name}] JSON_LIST_LENGTH={len(data)}"
                )
        except ValueError:
            print(f"[{name}] INVALID_JSON")

        return {
            "kind": kind,
            "job_ids": set(),
            "job_links": [],
        }

    if kind != "HTML":
        print(
            f"[{name}] preview="
            f"{result['content'][:180]!r}"
        )
        return {
            "kind": kind,
            "job_ids": set(),
            "job_links": [],
        }

    info = inspect_html(
        result["content"],
        result["url"],
    )

    ids = extract_job_ids(info["job_links"])

    print(f"[{name}] title={info['title']!r}")
    print(
        f"[{name}] links={len(info['links'])} "
        f"candidate_job_links={len(info['job_links'])} "
        f"unique_job_ids={len(ids)} "
        f"scripts={len(info['scripts'])} "
        f"forms={len(info['forms'])} "
        f"json_ld={len(info['json_ld'])}"
    )

    print(f"[{name}] markers={info['markers']}")
    print(
        f"[{name}] text_preview="
        f"{info['text_preview']!r}"
    )

    for url in info["job_links"][:8]:
        print(f"[{name}] JOB_LINK {url}")

    for script in info["scripts"][:8]:
        print(f"[{name}] SCRIPT {script}")

    for form in info["forms"][:3]:
        print(
            f"[{name}] FORM "
            f"{json.dumps(form, ensure_ascii=False)}"
        )

    for entry in info["json_ld"][:3]:
        if isinstance(entry, dict):
            print(
                f"[{name}] JSON_LD_TYPE="
                f"{entry.get('@type')}"
            )

    return {
        "kind": kind,
        "job_ids": ids,
        "job_links": info["job_links"],
    }


def compare_pages(results, left, right):
    a = results.get(left, {})
    b = results.get(right, {})

    a_ids = a.get("job_ids", set())
    b_ids = b.get("job_ids", set())

    print(
        f"[COMPARE] {left} vs {right}: "
        f"left_ids={len(a_ids)} "
        f"right_ids={len(b_ids)} "
        f"overlap={len(a_ids & b_ids)} "
        f"distinct={bool(a_ids or b_ids) and a_ids != b_ids}"
    )


def main():
    session = requests.Session()
    session.headers.update(HEADERS)

    results = {}

    for target in TARGETS:
        name = target["name"]
        url = target["url"]

        try:
            response = limited_get(session, url)
            results[name] = print_result(name, response)

        except requests.RequestException as exc:
            print(
                f"[{name}] REQUEST_ERROR "
                f"{type(exc).__name__}: {exc}"
            )

        except Exception as exc:
            print(
                f"[{name}] PARSE_ERROR "
                f"{type(exc).__name__}: {exc}"
            )

        time.sleep(DELAY_SECONDS)

    print("\n" + "=" * 72)
    print("COMPARISONS")
    print("=" * 72)

    compare_pages(
        results,
        "DELOITTE-INDIA-P0",
        "DELOITTE-INDIA-P25",
    )

    compare_pages(
        results,
        "DELOITTE-INDIA-P25",
        "DELOITTE-INDIA-P50",
    )

    print("\n[PROBE] Finished")


# ============================================================
# STALE ATS RECOVERY
# Read-only diagnostics for four existing company mappings.
# Run: python -u -m research.company_probe --stale-recovery
# ============================================================

RECOVERY_TARGETS = {
    "ATLASSIAN": "https://www.atlassian.com/company/careers/all-jobs",
    "COINDCX": "https://coindcx.com/opportunities",
    "ZEPTO": "https://www.zepto.com/s/careers",
}

POSTMAN_TENANT = "postman"
POSTMAN_CLUSTER = "wd108"
POSTMAN_BOARD = "careers"

RECOVERY_ROLE_PATTERN = re.compile(
    r"java|spring|backend|back.end|full.stack|"
    r"software engineer|developer|microservices",
    re.I,
)

RECOVERY_INDIA_PATTERN = re.compile(
    r"india|mumbai|navi mumbai|bengaluru|"
    r"bangalore|pune|hyderabad|chennai|noida",
    re.I,
)


def probe_postman_workday():
    """Validate Workday without changing the production registry."""
    from models.company import (
        Provider,
        ProviderConfig,
        ProviderStatus,
        ProviderType,
    )
    from research.loader import load_registry
    from src.providers.workday import WorkdayAdapter

    matches = [
        c for c in load_registry().companies
        if c.id == "postman"
    ]
    if len(matches) != 1:
        raise AssertionError("Expected one Postman registry entry")

    company = matches[0].model_copy(deep=True)
    company.provider = Provider(
        type=ProviderType.WORKDAY,
        status=ProviderStatus.PARTIAL,
        config=ProviderConfig(
            tenant="postman",
            cluster="wd108",
            board="careers",
        ),
    )

    adapter = WorkdayAdapter()
    started = time.perf_counter()
    jobs = adapter.fetch_jobs(company)

    urls = [str(job.url) for job in jobs]
    ids = [job.id for job in jobs]

    india = [
        job for job in jobs
        if RECOVERY_INDIA_PATTERN.search(job.location)
    ]
    relevant = [
        job for job in india
        if RECOVERY_ROLE_PATTERN.search(job.title)
    ]

    print(
        f"[POSTMAN] normalized={len(jobs)} "
        f"unique_ids={len(set(ids))} "
        f"unique_urls={len(set(urls))} "
        f"india={len(india)} "
        f"india_tech={len(relevant)} "
        f"seconds={time.perf_counter()-started:.2f}"
    )

    if (
        not jobs
        or len(set(ids)) != len(jobs)
        or len(set(urls)) != len(jobs)
    ):
        raise AssertionError(
            "Postman missing jobs or duplicate IDs/URLs"
        )

    expected_host = "postman.wd108.myworkdayjobs.com"

    for job in jobs:
        if (
            not job.id
            or not job.title.strip()
            or not job.location.strip()
        ):
            raise AssertionError(
                "Postman incomplete normalized job"
            )

        if urlparse(str(job.url)).hostname != expected_host:
            raise AssertionError(
                f"Unexpected Postman URL: {job.url}"
            )

    for job in relevant[:10]:
        print(
            f"[POSTMAN] INDIA_TECH "
            f"title={job.title!r} "
            f"location={job.location!r} "
            f"url={job.url}"
        )

    print(
        "[POSTMAN] ADAPTER_VALIDATION=PASS "
        "(listing total may change; no registry updates)"
    )


ATLASSIAN_DETAIL_RE = re.compile(
    r"^/company/careers/details/(\d+)/?$"
)


def atlassian_detail_links(links):
    """Extract canonical numeric detail links."""
    result = {}

    for link in links:
        parsed = urlparse(link)
        match = ATLASSIAN_DETAIL_RE.fullmatch(parsed.path)

        if (
            parsed.hostname == "www.atlassian.com"
            and match
        ):
            job_id = match.group(1)
            result[job_id] = (
                "https://www.atlassian.com/"
                f"company/careers/details/{job_id}"
            )

    return list(result.values())


def probe_atlassian_details(session):
    """Inspect three official Atlassian vacancies, read-only."""
    from bs4 import BeautifulSoup

    job_ids = {
        "27346": "Software Engineer II",
        "25540": "Backend Software Engineer II",
        "25561": "Full Stack Software Engineer",
    }

    base = "https://www.atlassian.com"
    detail_prefix = f"{base}/company/careers/details/"

    def clean(value, limit=300):
        return re.sub(r"\s+", " ", value or "").strip()[:limit]

    def show_element(label, element, limit=400):
        if element is None:
            return

        text = clean(element.get_text(" ", strip=True), limit)
        if not text:
            return

        classes = element.get("class") or []
        print(
            f"[ATLASSIAN_DETAIL] {label} "
            f"tag={element.name!r} "
            f"id={element.get('id')!r} "
            f"class={classes!r} "
            f"text={text!r}"
        )

    for job_id, expected_title in job_ids.items():
        url = f"{detail_prefix}{job_id}"
        print(
            f"\n[ATLASSIAN_DETAIL] job_id={job_id} "
            f"expected_title={expected_title!r}"
        )

        try:
            result = limited_get(session, url)
        except requests.RequestException as exc:
            print(
                f"[ATLASSIAN_DETAIL] REQUEST_ERROR "
                f"job_id={job_id} error={exc}"
            )
            continue

        print(
            f"[ATLASSIAN_DETAIL] status={result['status']} "
            f"bytes={result['bytes']} "
            f"truncated={result['truncated']} "
            f"final_url={result['url']}"
        )

        if result["status"] != 200 or result["truncated"]:
            print("[ATLASSIAN_DETAIL] PAGE_NOT_USABLE")
            continue

        soup = BeautifulSoup(
            result["content"],
            "html.parser",
        )

        # 1. Actual heading and surrounding job container.
        heading = soup.find(
            "h1",
            string=lambda text: (
                bool(text)
                and expected_title.casefold()
                in clean(text).casefold()
            ),
        )

        if heading is None:
            heading = soup.find("h1")

        show_element("HEADING", heading)

        if heading is not None:
            for parent in list(heading.parents)[:5]:
                if parent.name in ("html", "body"):
                    break

                show_element(
                    "HEADING_PARENT",
                    parent,
                    limit=180,
                )

        # 2. Scoped metadata candidates.
        selectors = {
            "MAIN": "main",
            "ARTICLE": "article",
            "JOB_CONTAINER": (
                '[class*="job-detail" i], '
                '[class*="job-description" i], '
                '[class*="job-content" i], '
                '[data-testid*="job" i]'
            ),
            "LOCATION": (
                '[class*="location" i], '
                '[data-testid*="location" i]'
            ),
            "DESCRIPTION": (
                'main [class*="description" i], '
                'article [class*="description" i]'
            ),
        }

        for label, selector in selectors.items():
            matches = soup.select(selector)

            print(
                f"[ATLASSIAN_DETAIL] {label}_COUNT="
                f"{len(matches)}"
            )

            for element in matches[:3]:
                show_element(label, element)

        # 3. Job-related embedded state clues.
        for script in soup.find_all("script"):
            script_id = script.get("id", "")
            script_type = script.get("type", "")
            content = script.string or ""

            if not content:
                continue

            markers = (
                "jobDescription",
                "jobLocation",
                "jobPosting",
                "requisitionId",
                "employmentType",
                "applyUrl",
                "applicationUrl",
            )

            matched = [
                marker
                for marker in markers
                if marker.casefold() in content.casefold()
            ]

            if not matched:
                continue

            print(
                "[ATLASSIAN_DETAIL] EMBEDDED_STATE "
                f"id={script_id!r} "
                f"type={script_type!r} "
                f"markers={matched}"
            )

            for marker in matched[:3]:
                match = re.search(
                    re.escape(marker),
                    content,
                    re.I,
                )

                if match:
                    start = max(0, match.start() - 100)
                    end = min(
                        len(content),
                        match.end() + 200,
                    )

                    print(
                        "[ATLASSIAN_DETAIL] STATE_CONTEXT "
                        f"marker={marker!r} "
                        f"text={clean(content[start:end], 300)!r}"
                    )

        # 4. Actual application-action candidates.
        application_links = []

        for anchor in soup.find_all("a", href=True):
            text = clean(
                anchor.get_text(" ", strip=True),
                80,
            )
            href = urljoin(result["url"], anchor["href"])

            if (
                re.search(r"\bapply(?:\s+now)?\b", text, re.I)
                or re.search(
                    r"/(?:apply|application)(?:/|\?|$)",
                    href,
                    re.I,
                )
            ):
                application_links.append((text, href))

        for text, href in application_links[:8]:
            print(
                "[ATLASSIAN_DETAIL] APPLY_LINK "
                f"text={text!r} url={href}"
            )

        # 5. Experience clues from the job-specific area.
        # Avoid treating global site navigation as a job description.
        scope = (
            heading.find_parent("main")
            if heading is not None
            else None
        ) or soup.find("main")

        if scope is not None:
            scoped_text = scope.get_text(" ", strip=True)

            experience_pattern = re.compile(
                r".{0,90}(?:"
                r"\d+\s*(?:\+|[-–]\s*\d+)?\s*years?"
                r"|experience required"
                r"|professional experience"
                r").{0,120}",
                re.I,
            )

            matches = experience_pattern.findall(
                scoped_text
            )

            for match in matches[:5]:
                print(
                    "[ATLASSIAN_DETAIL] EXPERIENCE "
                    f"{clean(match, 220)!r}"
                )

        print(
            f"[ATLASSIAN_DETAIL] job_id={job_id} "
            "INSPECTION_COMPLETE"
        )


def validate_atlassian_adapter():
    from research.loader import load_registry
    from src.providers.atlassian import AtlassianAdapter

    company = next(
        c for c in load_registry().companies
        if c.id == "atlassian"
    )

    company = company.model_copy(deep=True)

    if company.enabled:
        raise AssertionError(
            "Atlassian must remain disabled"
        )

    # Full-inventory validation only.
    # Does not modify config/companies.json.
    company.provider.config.detail_limit = None

    adapter = AtlassianAdapter()
    jobs = adapter.fetch_jobs(company)

    print(
        "[ATLASSIAN_ADAPTER] validation_scope="
        "FULL_INVENTORY"
    )

    ids = [job.id for job in jobs]
    urls = [str(job.url) for job in jobs]

    print(f"[ATLASSIAN_ADAPTER] jobs={len(jobs)}")
    print(
        f"[ATLASSIAN_ADAPTER] unique_ids={len(set(ids))}"
    )
    print(
        f"[ATLASSIAN_ADAPTER] unique_urls={len(set(urls))}"
    )

    if not jobs:
        raise AssertionError("No normalized Atlassian jobs")

    if len(ids) != len(set(ids)):
        raise AssertionError("Duplicate Atlassian IDs")

    if len(urls) != len(set(urls)):
        raise AssertionError("Duplicate Atlassian URLs")

    for job in jobs[:10]:
        print(
            "[ATLASSIAN_ADAPTER] SAMPLE "
            f"id={job.id} "
            f"title={job.title!r} "
            f"location={job.location!r} "
            f"url={job.url}"
        )

    print("[ATLASSIAN_ADAPTER] VALIDATION_COMPLETE")


def _atlassian_context(element, limit=500):
    parent = element.parent

    if parent is None:
        return ""

    return parent.get_text(" ", strip=True)[:limit]


def _atlassian_embedded_job_summaries(soup, limit=20):
    summaries = []

    def visit(value):
        if isinstance(value, dict):
            lowered_keys = {
                str(key).lower(): key
                for key in value
            }
            if any(
                key in lowered_keys
                for key in ("title", "jobtitle", "name")
            ) and any(
                token in " ".join(lowered_keys)
                for token in ("job", "location", "description")
            ):
                summaries.append({
                    str(key): value[key]
                    for key in value
                    if str(key).lower() in {
                        "title",
                        "jobtitle",
                        "name",
                        "location",
                        "locations",
                        "description",
                        "url",
                        "id",
                    }
                })

            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    for script in soup.find_all("script"):
        script_type = script.get("type", "").lower()
        script_id = script.get("id", "").lower()
        text = script.string or script.get_text()

        if not text or len(summaries) >= limit:
            continue

        if (
            script_type == "application/ld+json"
            or "json" in script_type
            or "state" in script_id
            or script_id in {"__next_data__", "__initial_state__"}
        ):
            try:
                visit(json.loads(text))
            except (ValueError, TypeError):
                continue

        if len(summaries) >= limit:
            break

    return summaries[:limit]


def probe_atlassian(session):
    url = RECOVERY_TARGETS["ATLASSIAN"]
    print(f"\n[ATLASSIAN] listing={url}")

    # Previous response exceeded the default 2 MB cap.
    # Raise it only for this listing request.
    global MAX_BYTES
    old_limit = MAX_BYTES

    try:
        MAX_BYTES = 6_000_000
        result = limited_get(session, url)
    finally:
        MAX_BYTES = old_limit

    print(
        f"[ATLASSIAN] status={result['status']} "
        f"bytes={result['bytes']} "
        f"truncated={result['truncated']}"
    )

    if result["status"] != 200 or result["truncated"]:
        print(
            "[ATLASSIAN] INCOMPLETE_LISTING "
            "- cannot certify inventory"
        )
        return

    info = inspect_html(
        result["content"],
        result["url"],
    )

    links = atlassian_detail_links(info["links"])
    soup = BeautifulSoup(result["content"], "html.parser")
    total_hints = []

    for tag in soup.select(
        '[data-total], [data-count], [aria-label], '
        'meta[name], meta[property]'
    ):
        value = " ".join(
            str(item)
            for item in (
                tag.get("data-total", ""),
                tag.get("data-count", ""),
                tag.get("aria-label", ""),
                tag.get("content", ""),
            )
        ).strip()

        if re.search(r"\b(?:349|jobs?|openings?|positions?)\b", value, re.I):
            total_hints.append(value[:250])

    print(
        f"[ATLASSIAN] strict_unique_job_links={len(links)} "
        "authoritative_total=UNKNOWN"
    )

    for hint in total_hints[:10]:
        print(f"[ATLASSIAN] LISTING_TOTAL_HINT {hint!r}")

    detail_link_set = set(links)
    for anchor in soup.find_all("a", href=True):
        absolute = urljoin(result["url"], anchor["href"])

        if absolute in detail_link_set:
            print(
                f"[ATLASSIAN] LISTING_JOB "
                f"url={absolute} "
                f"text={anchor.get_text(' ', strip=True)[:160]!r} "
                f"context={_atlassian_context(anchor)!r}"
            )

    for summary in _atlassian_embedded_job_summaries(soup):
        print(
            "[ATLASSIAN] EMBEDDED_JOB "
            f"{json.dumps(summary, ensure_ascii=False)[:700]}"
        )

    for link in links[:3]:
        detail = limited_get(session, link)

        print(
            f"[ATLASSIAN] detail_status={detail['status']} "
            f"url={detail['url']} "
            f"truncated={detail['truncated']}"
        )

        if (
            detail["status"] != 200
            or detail["truncated"]
        ):
            continue

        parsed = inspect_html(
            detail["content"],
            detail["url"],
        )
        detail_soup = BeautifulSoup(
            detail["content"],
            "html.parser",
        )

        jsonld_types = [
            item.get("@type")
            for item in parsed["json_ld"]
            if isinstance(item, dict)
        ]

        print(
            f"[ATLASSIAN] detail_title={parsed['title']!r} "
            f"jsonld_types={jsonld_types}"
        )

        for selector in (
            "h1",
            '[class*="title" i]',
            '[class*="location" i]',
            '[class*="description" i]',
        ):
            for element in detail_soup.select(selector)[:3]:
                text = element.get_text(" ", strip=True)

                if text:
                    print(
                        f"[ATLASSIAN] DETAIL_FIELD "
                        f"selector={selector!r} "
                        f"text={text[:500]!r}"
                    )

        for summary in _atlassian_embedded_job_summaries(
            detail_soup,
            limit=10,
        ):
            print(
                "[ATLASSIAN] DETAIL_EMBEDDED_JOB "
                f"{json.dumps(summary, ensure_ascii=False)[:700]}"
            )

        for candidate in parsed["links"]:
            if "apply" in candidate.lower():
                print(
                    "[ATLASSIAN] APPLY_CANDIDATE "
                    f"{candidate[:250]}"
                )
                break

    print(
        "[ATLASSIAN] PROBE_REQUIRED: detail normalization "
        "and authoritative completeness not established"
    )


def probe_recovery_html(name, url, session):
    print(f"\n[RECOVERY] {name}")
    print(f"[{name}] requested={url}")

    try:
        result = limited_get(session, url)

        print(
            f"[{name}] status={result['status']} "
            f"final={result['url']} "
            f"type={result['type']!r} "
            f"bytes={result['bytes']} "
            f"truncated={result['truncated']}"
        )

        kind = classify_page(result)
        print(f"[{name}] classification={kind}")

        if kind != "HTML":
            print(
                f"[{name}] HTML inventory unavailable; "
                "ATS remains unverified"
            )
            return

        info = inspect_html(
            result["content"],
            result["url"],
        )

        print(
            f"[{name}] title={info['title']!r} "
            f"links={len(info['links'])} "
            f"candidate_job_links={len(info['job_links'])} "
            f"scripts={len(info['scripts'])} "
            f"forms={len(info['forms'])} "
            f"json_ld={len(info['json_ld'])}"
        )

        print(f"[{name}] markers={info['markers']}")

        for link in info["job_links"][:20]:
            print(f"[{name}] JOB_LINK {link}")

        for script in info["scripts"][:10]:
            print(f"[{name}] SCRIPT {script}")

        for form in info["forms"][:5]:
            print(
                f"[{name}] FORM "
                f"{json.dumps(form, ensure_ascii=False)}"
            )

        for entry in info["json_ld"][:5]:
            if isinstance(entry, dict):
                print(
                    f"[{name}] JSONLD "
                    f"type={entry.get('@type')!r}"
                )

        # Additional same-site link discovery, useful when
        # the current careers page is only a landing page.
        base_host = urlparse(result["url"]).hostname

        candidate_links = [
            link for link in info["links"]
            if urlparse(link).hostname == base_host
            and any(
                token in urlparse(link).path.lower()
                for token in (
                    "career",
                    "opening",
                    "position",
                    "job",
                    "apply",
                )
            )
        ]

        for link in candidate_links[:15]:
            print(f"[{name}] CAREER_CANDIDATE {link}")

        print(
            f"[{name}] observed_job_links="
            f"{len(info['job_links'])} "
            "authoritative_total=UNKNOWN "
            "exhaustive_inventory=NO"
        )

    except requests.RequestException as exc:
        print(
            f"[{name}] REQUEST_ERROR "
            f"{type(exc).__name__}: {exc}"
        )


def run_stale_recovery():
    print("=" * 70)
    print("STALE ATS RECOVERY - READ ONLY")
    print("=" * 70)

    # Postman: complete adapter validation.
    try:
        probe_postman_workday()
    except Exception as exc:
        print(
            f"[POSTMAN] VALIDATION_FAILED "
            f"{type(exc).__name__}: {exc}"
        )

    session = requests.Session()
    session.headers.update(HEADERS)

    # Atlassian: validate the bounded adapter configuration.
    try:
        validate_atlassian_adapter()
    except Exception as exc:
        print(
            "[ATLASSIAN_ADAPTER] VALIDATION_FAILED "
            f"{type(exc).__name__}: {exc}"
        )
        raise

    # Avoid repeating previously blocked requests.
    print(
        "[COINDCX] UNRESOLVED: prior official page "
        "returned HTTP 403"
    )
    print(
        "[ZEPTO] UNRESOLVED: prior official page "
        "returned AWS WAF challenge"
    )

    print("\n[RECOVERY] COMPLETE")
    print("[RECOVERY] No registry or state changes")
    print("[RECOVERY] No Telegram notifications")
    print("[RECOVERY] No automatic ATS replacement")


# ============================================================
# NEW COMPANY RESEARCH
# Duck Creek, Baker Hughes, Mphasis
# Run: python -u -m research.company_probe --new-companies
# ============================================================

NEW_COMPANY_SOURCES = {
    "DUCKCREEK": {
        "tenant": "duckcreek",
        "cluster": "wd1",
        "board": "duckcreekcareers",
    },
    "BAKERHUGHES": {
        # Candidate source only; inventory not verified.
        "tenant": "bakerhughes",
        "cluster": "wd5",
        "board": "BakerHughes",
    },
}

NEW_COMPANY_PAGES = {
    "DUCKCREEK_CAREERS": "https://www.duckcreek.com/careers/",
    "BAKERHUGHES_CAREERS": "https://careers.bakerhughes.com/global/en",
    "MPHASIS_CAREERS": "https://careers.mphasis.com/home.html",
    "MPHASIS_HOTJOBS": "https://www2.mphasis.com/hot-jobs.html",
    "MPHASIS_RIPPLEHIRE": "https://mphasis.ripplehire.com/candidate/",
}

NEW_COMPANY_ROLE_RE = re.compile(
    r"java|spring|backend|back.end|full.stack|"
    r"software engineer|developer|microservices",
    re.I,
)

NEW_COMPANY_INDIA_RE = re.compile(
    r"india|mumbai|navi mumbai|bengaluru|"
    r"bangalore|hyderabad|pune|chennai|noida",
    re.I,
)


def probe_new_workday(name, config, session):
    """Inspect two public CXS pages; do not change registry."""
    tenant = config["tenant"]
    cluster = config["cluster"]
    board = config["board"]

    base = (
        f"https://{tenant}.{cluster}.myworkdayjobs.com"
    )
    endpoint = (
        f"{base}/wday/cxs/{tenant}/{board}/jobs"
    )

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Origin": base,
        "Referer": f"{base}/en-US/{board}",
    }

    page_paths = {}
    reported_totals = []

    print(f"\n[{name}] WORKDAY_CANDIDATE={endpoint}")

    for offset in (0, 20):
        try:
            response = session.post(
                endpoint,
                json={
                    "appliedFacets": {},
                    "limit": 20,
                    "offset": offset,
                    "searchText": "",
                },
                headers=headers,
                timeout=TIMEOUT,
            )

            print(
                f"[{name}] offset={offset} "
                f"status={response.status_code} "
                f"content_type="
                f"{response.headers.get('Content-Type')!r}"
            )

            response.raise_for_status()

            data = response.json()
            if not isinstance(data, dict):
                raise ValueError(
                    "Expected Workday JSON object"
                )

            postings = data.get("jobPostings")
            if not isinstance(postings, list):
                raise ValueError(
                    "Missing jobPostings list"
                )

            paths = [
                str(item["externalPath"])
                for item in postings
                if isinstance(item, dict)
                and item.get("externalPath")
            ]

            page_paths[offset] = set(paths)

            total = data.get("total")
            reported_totals.append(total)

            print(
                f"[{name}] offset={offset} "
                f"total={total!r} "
                f"count={len(postings)} "
                f"unique_paths={len(set(paths))}"
            )

            india_count = 0
            relevant_count = 0

            for item in postings:
                title = str(item.get("title", ""))
                location = str(
                    item.get("locationsText", "")
                )

                if NEW_COMPANY_INDIA_RE.search(location):
                    india_count += 1

                    if NEW_COMPANY_ROLE_RE.search(title):
                        relevant_count += 1

            print(
                f"[{name}] offset={offset} "
                f"india_observed={india_count} "
                f"india_tech_observed={relevant_count}"
            )

            for item in postings[:5]:
                print(
                    f"[{name}] SAMPLE "
                    f"title={item.get('title')!r} "
                    f"location={item.get('locationsText')!r} "
                    f"path={item.get('externalPath')!r}"
                )

        except (
            requests.RequestException,
            ValueError,
        ) as exc:
            print(
                f"[{name}] offset={offset} "
                f"ERROR={type(exc).__name__}: {exc}"
            )

    if 0 in page_paths and 20 in page_paths:
        overlap = page_paths[0] & page_paths[20]

        print(
            f"[{name}] page_overlap={len(overlap)} "
            f"distinct_pages="
            f"{page_paths[0] != page_paths[20]}"
        )

    print(
        f"[{name}] reported_totals={reported_totals} "
        "exhaustive_inventory=NO "
        "adapter_validation=PENDING"
    )


def validate_new_workday(name, config):
    """Validate a Workday candidate with the production adapter."""
    from models.company import (
        Company,
        CompanyCategory,
        Provider,
        ProviderConfig,
        ProviderStatus,
        ProviderType,
    )
    from src.providers.workday import WorkdayAdapter

    tenant = config["tenant"]
    cluster = config["cluster"]
    board = config["board"]
    base = (
        f"https://{tenant}."
        f"{cluster}.myworkdayjobs.com"
    )
    display_names = {
        "DUCKCREEK": "Duck Creek",
        "BAKERHUGHES": "Baker Hughes",
    }
    display_name = display_names.get(name, name)

    company = Company(
        id=name.lower(),
        name=display_name,
        category=CompanyCategory.PRODUCT,
        priority=1,
        enabled=False,
        career_page=f"{base}/en-US/{board}",
        provider=Provider(
            type=ProviderType.WORKDAY,
            status=ProviderStatus.PARTIAL,
            config=ProviderConfig(
                tenant=tenant,
                cluster=cluster,
                board=board,
            ),
        ),
    )

    started = time.perf_counter()
    jobs = WorkdayAdapter().fetch_jobs(company)
    elapsed = time.perf_counter() - started

    ids = [str(job.id) for job in jobs]
    urls = [str(job.url) for job in jobs]
    problems = []

    print(
        f"[{name}] normalized={len(jobs)} "
        f"unique_ids={len(set(ids))} "
        f"unique_urls={len(set(urls))} "
        f"seconds={elapsed:.2f}"
    )

    if not jobs:
        problems.append("no normalized jobs")

    if len(set(ids)) != len(jobs):
        problems.append("duplicate normalized IDs")

    if len(set(urls)) != len(jobs):
        problems.append("duplicate normalized URLs")

    expected_host = (
        f"{tenant}.{cluster}.myworkdayjobs.com"
    )

    for job in jobs:
        if not job.id or not job.title.strip() or not job.location.strip():
            problems.append(
                f"incomplete normalized job: {job.id!r}"
            )
            continue

        if urlparse(str(job.url)).hostname != expected_host:
            problems.append(
                f"unexpected job URL host: {job.url}"
            )

    # Independently check the current first-page total.
    base = (
        f"https://{config['tenant']}."
        f"{config['cluster']}.myworkdayjobs.com"
    )
    endpoint = (
        f"{base}/wday/cxs/{config['tenant']}/"
        f"{config['board']}/jobs"
    )

    try:
        response = requests.post(
            endpoint,
            json={
                "appliedFacets": {},
                "limit": 20,
                "offset": 0,
                "searchText": "",
            },
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Origin": base,
                "Referer": (
                    f"{base}/en-US/{config['board']}"
                ),
            },
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()

        if not isinstance(data, dict):
            raise ValueError(
                "expected Workday JSON object"
            )

        reported_total = data.get("total")

        print(
            f"[{name}] authoritative_total="
            f"{reported_total!r}"
        )

        if (
            not isinstance(reported_total, int)
            or reported_total < 0
        ):
            problems.append("invalid reported total")
        elif len(jobs) != reported_total:
            problems.append(
                f"total mismatch: "
                f"expected={reported_total}, "
                f"normalized={len(jobs)}"
            )

    except (requests.RequestException, ValueError) as exc:
        problems.append(
            f"total verification failed: {exc}"
        )

    if problems:
        for problem in problems:
            print(f"[{name}] VALIDATION_PROBLEM {problem}")
        return False

    print(f"[{name}] ADAPTER_VALIDATION=PASS")
    return True


def probe_new_company_page(name, url, session):
    """Inspect official public pages without guessing APIs."""
    print(f"\n[{name}] requested={url}")

    try:
        result = limited_get(session, url)

        print(
            f"[{name}] status={result['status']} "
            f"final={result['url']} "
            f"type={result['type']!r} "
            f"bytes={result['bytes']} "
            f"truncated={result['truncated']} "
            f"redirects={result['redirects']}"
        )

        kind = classify_page(result)
        print(f"[{name}] classification={kind}")

        if kind != "HTML":
            print(
                f"[{name}] inventory=UNVERIFIED"
            )
            return

        info = inspect_html(
            result["content"],
            result["url"],
        )

        print(
            f"[{name}] title={info['title']!r} "
            f"links={len(info['links'])} "
            f"job_candidates={len(info['job_links'])} "
            f"scripts={len(info['scripts'])} "
            f"jsonld={len(info['json_ld'])}"
        )

        for link in info["job_links"][:10]:
            print(f"[{name}] JOB_CANDIDATE {link}")

        # Officially linked recruitment destinations only.
        ats_links = [
            link
            for link in info["links"]
            if any(
                token in (
                    urlparse(link).hostname or ""
                ).lower()
                for token in (
                    "myworkdayjobs.com",
                    "ripplehire.com",
                    "icims.com",
                    "greenhouse.io",
                    "lever.co",
                    "ashbyhq.com",
                )
            )
        ]

        for link in ats_links[:10]:
            print(f"[{name}] ATS_LINK {link}")

        for entry in info["json_ld"][:5]:
            if isinstance(entry, dict):
                print(
                    f"[{name}] JSONLD "
                    f"type={entry.get('@type')!r}"
                )

        print(
            f"[{name}] authoritative_total=UNKNOWN "
            "pagination_verified=NO "
            "exhaustive_inventory=NO"
        )

    except requests.RequestException as exc:
        print(
            f"[{name}] REQUEST_ERROR "
            f"{type(exc).__name__}: {exc}"
        )


def probe_mphasis_sources(session):
    """Inspect officially published RippleHire sources."""
    print("\n[MPHASIS] DEEP_SOURCE_DISCOVERY")

    sources = [
        (
            "RIPPLEHIRE_CAREERS",
            "https://mphasis.ripplehire.com/ripplehire/careers",
        ),
        (
            "RIPPLEHIRE_CANDIDATE",
            "https://mphasis.ripplehire.com/candidate/",
        ),
        (
            "OFFICIAL_HOTJOBS",
            "https://www2.mphasis.com/hot-jobs.html",
        ),
    ]

    for label, url in sources:
        try:
            result = limited_get(session, url)

            print(
                f"[MPHASIS] source={label} "
                f"status={result['status']} "
                f"final={result['url']} "
                f"bytes={result['bytes']} "
                f"truncated={result['truncated']}"
            )

            if (
                result["status"] != 200
                or classify_page(result) != "HTML"
            ):
                continue

            info = inspect_html(
                result["content"],
                result["url"],
            )

            print(
                f"[MPHASIS] source={label} "
                f"links={len(info['links'])} "
                f"scripts={len(info['scripts'])} "
                f"jsonld={len(info['json_ld'])}"
            )

            for link in info["links"]:
                host = (
                    urlparse(link).hostname or ""
                ).lower()

                if (
                    host == "r.ripplehire.com"
                    or host == "mphasis.ripplehire.com"
                ):
                    print(
                        f"[MPHASIS] OFFICIAL_ATS_LINK "
                        f"{link}"
                    )

            # Inspect a bounded set of script references.
            # Do not fetch arbitrary scripts or guess APIs.
            for script in info["scripts"][:8]:
                print(
                    f"[MPHASIS] SCRIPT_REFERENCE "
                    f"{script}"
                )

            if label == "OFFICIAL_HOTJOBS":
                short_links = [
                    link
                    for link in info["links"]
                    if (
                        urlparse(link).hostname
                        == "r.ripplehire.com"
                    )
                ]

                for link in list(
                    dict.fromkeys(short_links)
                )[:3]:
                    try:
                        redirected = limited_get(
                            session, link
                        )

                        print(
                            "[MPHASIS] HOTJOB_REDIRECT "
                            f"source={link} "
                            f"status={redirected['status']} "
                            f"final={redirected['url']}"
                        )

                    except requests.RequestException as exc:
                        print(
                            "[MPHASIS] HOTJOB_ERROR "
                            f"{type(exc).__name__}: {exc}"
                        )

        except requests.RequestException as exc:
            print(
                f"[MPHASIS] SOURCE_ERROR "
                f"source={label} "
                f"{type(exc).__name__}: {exc}"
            )

    print(
        "[MPHASIS] inventory_contract=UNVERIFIED "
        "pagination=UNVERIFIED"
    )


def run_new_companies():
    print("=" * 70)
    print("NEW COMPANY ATS VALIDATION - READ ONLY")
    print("=" * 70)

    results = {}

    # Full Workday adapter validation.
    for name in ("DUCKCREEK", "BAKERHUGHES"):
        config = NEW_COMPANY_SOURCES[name]

        try:
            results[name] = validate_new_workday(
                name, config
            )
        except Exception as exc:
            results[name] = False
            print(
                f"[{name}] VALIDATION_FAILED "
                f"{type(exc).__name__}: {exc}"
            )

        time.sleep(DELAY_SECONDS)

    # Mphasis official-source investigation.
    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        probe_mphasis_sources(session)
        results["MPHASIS"] = None
    except Exception as exc:
        results["MPHASIS"] = False
        print(
            "[MPHASIS] DISCOVERY_FAILED "
            f"{type(exc).__name__}: {exc}"
        )
    finally:
        session.close()

    print("\n[NEW_COMPANIES] SUMMARY")

    for name, result in results.items():
        status = (
            "ADAPTER_PASS"
            if result is True
            else "PROBE_REQUIRED"
            if result is None
            else "VALIDATION_FAILED"
        )

        print(
            f"[NEW_COMPANIES] {name}={status}"
        )

    print("[NEW_COMPANIES] No registry changes")
    print("[NEW_COMPANIES] No state writes")
    print("[NEW_COMPANIES] No Telegram notifications")
    print("[NEW_COMPANIES] No automatic activation")

    if any(result is False for result in results.values()):
        raise RuntimeError(
            "One or more company validations failed"
        )


def probe_workday_location_details():
    """Inspect public Workday detail-location fields, read-only."""
    import requests

    targets = {
        "DUCKCREEK": {
            "tenant": "duckcreek",
            "cluster": "wd1",
            "board": "duckcreekcareers",
            "paths": [
                "/job/Mumbai-India/Software-Engineer-II_REQID55166-1",
                "/job/Bengaluru-India/Senior-Associate-Software-Engineer_REQID55208-1",
            ],
        },
        "BAKERHUGHES": {
            "tenant": "bakerhughes",
            "cluster": "wd5",
            "board": "BakerHughes",
            "paths": [
                "/job/IN-MH-MUMBAI-HIRANANDANI-BUSINESS-PARK-POWAI/Engineering-Specialist---Applications-and-Software_R160606",
                "/job/IN-MH-MUMBAI-HIRANANDANI-BUSINESS-PARK-POWAI/Digital-Technology-Professional---Software-Engineering_R169599-1",
            ],
        },
    }

    print("[WORKDAY_LOCATION] READ_ONLY")

    for company_name, config in targets.items():
        base = (
            f"https://{config['tenant']}."
            f"{config['cluster']}.myworkdayjobs.com"
        )

        for path in config["paths"]:
            # Candidate CXS detail path derived from a verified
            # public Workday job path; response unverified.
            url = (
                f"{base}/wday/cxs/"
                f"{config['tenant']}/"
                f"{config['board']}"
                f"{path}"
            )

            try:
                response = requests.get(
                    url,
                    headers={"Accept": "application/json"},
                    timeout=20,
                )

                print(
                    f"[WORKDAY_LOCATION] company={company_name} "
                    f"status={response.status_code} "
                    f"content_type="
                    f"{response.headers.get('Content-Type')!r}"
                )

                if response.status_code != 200:
                    continue

                data = response.json()

                if not isinstance(data, dict):
                    print(
                        "[WORKDAY_LOCATION] "
                        "unexpected_response_shape"
                    )
                    continue

                print(
                    f"[WORKDAY_LOCATION] "
                    f"top_level_keys={sorted(data.keys())}"
                )

                job_posting = data.get("jobPostingInfo", {})

                if not isinstance(job_posting, dict):
                    continue

                print(
                    f"[WORKDAY_LOCATION] "
                    f"job_fields={sorted(job_posting.keys())}"
                )

                for key, value in job_posting.items():
                    if any(
                        marker in key.casefold()
                        for marker in (
                            "location",
                            "country",
                            "region",
                            "city",
                            "remote",
                        )
                    ):
                        print(
                            "[WORKDAY_LOCATION] "
                            f"field={key!r} "
                            f"value={str(value)[:500]!r}"
                        )

            except (
                requests.RequestException,
                ValueError,
            ) as exc:
                print(
                    f"[WORKDAY_LOCATION] "
                    f"company={company_name} "
                    f"error={type(exc).__name__}: {exc}"
                )

    print("[WORKDAY_LOCATION] COMPLETE")


def run_activation_check():
    """Read-only activation check using production filter rules."""
    probe_workday_location_details()

    from collections import Counter

    from research.loader import load_registry
    from src.filters import JobFilter
    from src.providers.workday import WorkdayAdapter

    targets = {
        "duckcreek": "DUCKCREEK",
        "bakerhughes": "BAKERHUGHES",
    }

    registry = load_registry()
    job_filter = JobFilter()
    adapter = WorkdayAdapter()
    results = {}

    print("=" * 70)
    print("WORKDAY ACTIVATION READINESS - READ ONLY")
    print("=" * 70)

    for company_id, label in targets.items():
        matches = [
            company
            for company in registry.companies
            if company.id == company_id
        ]

        if len(matches) != 1:
            print(
                f"[{label}] REGISTRY_ERROR "
                f"expected=1 found={len(matches)}"
            )
            results[label] = "REVIEW"
            continue

        company = matches[0].model_copy(deep=True)

        if company.enabled:
            print(
                f"[{label}] WARNING "
                "company is already enabled"
            )
            results[label] = "REVIEW"
            continue

        print(f"\n[{label}] fetching jobs")

        try:
            jobs = adapter.fetch_jobs(company)
        except Exception as exc:
            print(
                f"[{label}] FETCH_FAILED "
                f"{type(exc).__name__}: {exc}"
            )
            results[label] = "REVIEW"
            continue

        reasons = Counter()
        included = []
        ambiguous = []
        india_candidates = []

        ids = [str(job.id) for job in jobs]
        urls = [str(job.url) for job in jobs]

        for job in jobs:
            evaluation = job_filter.evaluate(job)

            if evaluation.included:
                included.append(job)
            else:
                reason = (
                    evaluation.reason.value
                    if evaluation.reason
                    else "unknown"
                )
                reasons[reason] += 1

            location = str(job.location)
            title = str(job.title)
            url = str(job.url)

            # Diagnostic only: this is not a replacement
            # for the production location filter.
            india_hint = bool(
                NEW_COMPANY_INDIA_RE.search(location)
                or re.search(
                    r"/(?:Mumbai|Navi-Mumbai|Bengaluru|"
                    r"Bangalore|Remote)-India/",
                    url,
                    re.I,
                )
                or re.search(
                    r"/IN-[A-Z]{2}-",
                    url,
                    re.I,
                )
            )

            if india_hint:
                india_candidates.append(job)

            if re.fullmatch(
                r"\d+\s+Locations?",
                location,
                re.I,
            ):
                ambiguous.append(job)

        print(
            f"[{label}] fetched={len(jobs)} "
            f"unique_ids={len(set(ids))} "
            f"unique_urls={len(set(urls))}"
        )

        print(
            f"[{label}] filter_matches={len(included)} "
            f"filter_rejected={len(jobs)-len(included)}"
        )

        print(
            f"[{label}] india_candidates="
            f"{len(india_candidates)} "
            f"ambiguous_locations={len(ambiguous)}"
        )

        print(
            f"[{label}] rejection_reasons="
            f"{dict(sorted(reasons.items()))}"
        )

        for job in included[:12]:
            print(
                f"[{label}] MATCH "
                f"id={job.id!r} "
                f"title={job.title!r} "
                f"location={job.location!r} "
                f"url={job.url}"
            )

        # Prioritize ambiguous locations with relevant titles.
        relevant_ambiguous = [
            job for job in ambiguous
            if NEW_COMPANY_ROLE_RE.search(job.title)
        ]

        for job in relevant_ambiguous[:15]:
            evaluation = job_filter.evaluate(job)

            print(
                f"[{label}] AMBIGUOUS "
                f"id={job.id!r} "
                f"title={job.title!r} "
                f"location={job.location!r} "
                f"reason="
                f"{evaluation.reason.value if evaluation.reason else 'included'} "
                f"url={job.url}"
            )

        for job in india_candidates[:10]:
            evaluation = job_filter.evaluate(job)

            print(
                f"[{label}] INDIA_CANDIDATE "
                f"id={job.id!r} "
                f"title={job.title!r} "
                f"location={job.location!r} "
                f"filter_included={evaluation.included} "
                f"reason="
                f"{evaluation.reason.value if evaluation.reason else 'none'}"
            )

        valid_identity = (
            bool(jobs)
            and len(ids) == len(set(ids))
            and len(urls) == len(set(urls))
        )

        if not valid_identity:
            results[label] = "REVIEW"
        elif relevant_ambiguous:
            results[label] = "LOCATION_REVIEW"
        elif label == "BAKERHUGHES":
            results[label] = "SOURCE_COMPARISON_PENDING"
        else:
            results[label] = "FILTER_CHECK_PASS"

    print("\n[ACTIVATION] SUMMARY")

    for label, status in results.items():
        print(
            f"[ACTIVATION] {label}={status}"
        )

    print("[ACTIVATION] No registry modifications")
    print("[ACTIVATION] No seen/recovery state writes")
    print("[ACTIVATION] No Telegram notifications")

    if any(
        status == "REVIEW"
        for status in results.values()
    ):
        raise RuntimeError(
            "Activation validation encountered errors"
        )


# ============================================================
# CRISIL / CLOVER INFOTECH / TECH MAHINDRA
# Consolidated public careers research
# ============================================================

COMPANY_BATCH_TARGETS = {
    "CRISIL": [
        "https://www.crisil.com/en/home/careers.html",
        "https://career.crisil.com/crisil/",
    ],
    "CLOVER": [
        "https://www.cloverinfotech.com/careers/",
        "https://www.cloverinfotech.com/job-openings/",
        "https://www.cloverinfotech.com/jobs/",
    ],
    "TECHMAHINDRA": [
        "https://careers.techmahindra.com/",
        "https://careers.techmahindra.com/CurrentOpportunity.aspx",
    ],
}

_COMPANY_BATCH_ROLE_RE = re.compile(
    r"java|spring|backend|back.end|full.stack|"
    r"software engineer|software developer|react|"
    r"microservices|application developer",
    re.I,
)

_COMPANY_BATCH_INDIA_RE = re.compile(
    r"india|mumbai|navi.mumbai|bengaluru|"
    r"bangalore|hyderabad|pune|chennai|noida",
    re.I,
)

_TECH_MAHINDRA_URL = (
    "https://careers.techmahindra.com/"
    "CurrentOpportunity.aspx"
)

_TM_ROLE_RE = re.compile(
    r"java|spring|full[\s-]?stack|backend|"
    r"back[\s-]?end|software developer|"
    r"software engineer|react|microservices",
    re.I,
)

_TM_INDIA_RE = re.compile(
    r"mumbai|navi mumbai|bengaluru|bangalore|"
    r"hyderabad|pune|chennai|noida|india",
    re.I,
)


def extract_techmahindra_jobs(html: str) -> list[dict]:
    """Extract job cards from the verified ASP.NET DataList."""
    soup = BeautifulSoup(html, "html.parser")

    table = soup.select_one(
        '[id$="DataListRecommended"]'
    )

    if table is None:
        return []

    jobs = []
    seen = set()

    for hidden in table.select(
        'input[type="hidden"][name$="HdnJobCode"]'
    ):
        job_id = (hidden.get("value") or "").strip()

        if not job_id or job_id in seen:
            continue

        # Each repeated job is rendered inside a table cell.
        card = hidden.find_parent("td")

        if card is None:
            continue

        text = re.sub(
            r"\s+",
            " ",
            card.get_text(" ", strip=True),
        )

        if not text:
            continue

        button = card.select_one(
            'input[name$="btn_jobs"],'
            'button[name$="btn_jobs"]'
        )

        if button is None:
            continue

        name = button.get("name", "")

        # Keep raw text as evidence. Field extraction is
        # best-effort until the actual card DOM is confirmed.
        skill = re.search(
            r"Skill\s*Set\s*:\s*(.*?)"
            r"(?=\s*Experience\s*:|$)",
            text,
            re.I,
        )
        experience = re.search(
            r"Experience\s*:\s*(.*?)"
            r"(?=\s*Location\s*:|$)",
            text,
            re.I,
        )
        location = re.search(
            r"Location\s*:\s*(.*)$",
            text,
            re.I,
        )

        title = re.split(
            r"\bSkill\s*Set\s*:",
            text,
            maxsplit=1,
            flags=re.I,
        )[0].strip()

        jobs.append({
            "id": job_id,
            "title": title,
            "skills": (
                skill.group(1).strip()
                if skill else ""
            ),
            "experience": (
                experience.group(1).strip()
                if experience else ""
            ),
            "location": (
                location.group(1).strip()
                if location else ""
            ),
            "button_name": name,
            "button_value": button.get("value", ""),
        })

        seen.add(job_id)

    return jobs


def summarize_techmahindra_jobs(
    label: str,
    jobs: list[dict],
) -> None:
    """Report bounded India/technology evidence."""
    relevant = []

    for job in jobs:
        title = job["title"]
        skills = job["skills"]
        location = job["location"]

        if (
            _TM_ROLE_RE.search(title + " " + skills)
            and _TM_INDIA_RE.search(location)
        ):
            relevant.append(job)

    print(
        f"[TECHMAHINDRA] {label} "
        f"jobs={len(jobs)} "
        f"unique_ids={len({j['id'] for j in jobs})} "
        f"india_tech={len(relevant)}"
    )

    for job in relevant[:12]:
        print(
            "[TECHMAHINDRA] INDIA_TECH "
            f"id={job['id']!r} "
            f"title={job['title']!r} "
            f"skills={job['skills']!r} "
            f"experience={job['experience']!r} "
            f"location={job['location']!r}"
        )


def _tm_form_payload(
    html: str,
    button_name: str | None = None,
    button_value: str = "",
    event_target: str = "",
) -> dict:
    """Build a public Web Forms navigation payload."""
    soup = BeautifulSoup(html, "html.parser")
    form = soup.select_one("form")

    if form is None:
        raise ValueError("ASP.NET form not found")

    payload = {}

    # Preserve page-provided state for this session.
    # Never print these values.
    for field in form.select("input[name]"):
        name = field.get("name", "")
        kind = field.get("type", "text").lower()

        if kind in ("hidden", "text"):
            payload[name] = field.get("value", "")

    payload["__EVENTTARGET"] = event_target
    payload["__EVENTARGUMENT"] = ""

    if button_name:
        payload[button_name] = button_value

    return payload


def probe_techmahindra_navigation(session) -> None:
    """Verify one public pager without triggering a job action."""
    print("\n[TECHMAHINDRA] NAVIGATION_VALIDATION")

    response = session.get(
        _TECH_MAHINDRA_URL,
        timeout=TIMEOUT,
    )
    response.raise_for_status()

    initial_html = response.text
    initial_jobs = extract_techmahindra_jobs(
        initial_html
    )

    summarize_techmahindra_jobs(
        "PAGE_1", initial_jobs
    )

    if not initial_jobs:
        print(
            "[TECHMAHINDRA] "
            "BLOCKER=NO_STRUCTURED_JOB_CARDS"
        )
        return

    soup = BeautifulSoup(
        initial_html,
        "html.parser",
    )

    pager = None

    for anchor in soup.select("a[href]"):
        if anchor.get_text(" ", strip=True) != "2":
            continue

        href = anchor.get("href", "")

        match = re.search(
            r"__doPostBack\('([^']+)','([^']*)'\)",
            href,
        )

        if match:
            pager = match
            break

    if pager is None:
        print(
            "[TECHMAHINDRA] "
            "PAGE_2=NOT_AVAILABLE"
        )
    else:
        payload = _tm_form_payload(
            initial_html,
            event_target=pager.group(1),
        )
        payload["__EVENTARGUMENT"] = pager.group(2)

        page2_response = session.post(
            _TECH_MAHINDRA_URL,
            data=payload,
            timeout=TIMEOUT,
            allow_redirects=True,
        )
        page2_response.raise_for_status()

        page2_jobs = extract_techmahindra_jobs(
            page2_response.text
        )

        first_ids = {
            job["id"] for job in initial_jobs
        }
        second_ids = {
            job["id"] for job in page2_jobs
        }

        summarize_techmahindra_jobs(
            "PAGE_2", page2_jobs
        )

        print(
            "[TECHMAHINDRA] PAGINATION "
            f"page1={len(first_ids)} "
            f"page2={len(second_ids)} "
            f"overlap={len(first_ids & second_ids)} "
            f"distinct={bool(second_ids - first_ids)}"
        )

    # The btn_jobs handler has not been verified as a read-only
    # detail action, so do not submit it.
    print(
        "[TECHMAHINDRA] DETAIL_NAVIGATION=SKIPPED "
        "reason=button_behavior_unverified "
        "canonical_url=NOT_VERIFIED"
    )


def inspect_company_page_structure(
    name: str,
    content: str,
    base_url: str,
) -> dict:
    """Inspect public careers HTML without submitting forms."""
    soup = BeautifulSoup(content, "html.parser")

    result = {
        "forms": [],
        "tables": [],
        "pagination": [],
        "job_references": [],
        "scripts": [],
        "embedded_markers": [],
    }

    # 1. Forms and public field names.
    for form in soup.select("form")[:8]:
        action = urljoin(
            base_url,
            form.get("action") or base_url,
        )
        parsed_action = urlparse(action)
        safe_action = parsed_action._replace(
            query="",
            fragment="",
        ).geturl()

        fields = []
        hidden_names = []

        for control in form.select(
            "input[name], select[name], textarea[name]"
        ):
            field_name = control.get("name", "")
            field_type = control.get(
                "type", control.name
            ).lower()

            if field_type == "hidden":
                hidden_names.append(field_name)
            else:
                fields.append({
                    "name": field_name,
                    "type": field_type,
                })

        result["forms"].append({
            "action": safe_action,
            "method": form.get(
                "method", "GET"
            ).upper(),
            "fields": fields[:30],
            "hidden_names": hidden_names[:30],
        })

    # 2. Table structure and bounded row samples.
    for table in soup.select("table")[:12]:
        headers = [
            th.get_text(" ", strip=True)
            for th in table.select("th")
        ][:15]

        rows = []

        for tr in table.select("tr")[:6]:
            cells = [
                re.sub(
                    r"\s+", " ",
                    td.get_text(" ", strip=True),
                )[:120]
                for td in tr.select("td")
            ]

            if cells:
                rows.append(cells[:12])

        if headers or rows:
            result["tables"].append({
                "id": table.get("id", ""),
                "headers": headers,
                "rows": rows,
                "row_count_in_html": len(
                    table.select("tr")
                ),
            })

    # 3. Real navigation links and ASP.NET postbacks.
    for anchor in soup.select("a")[:500]:
        label = re.sub(
            r"\s+", " ",
            anchor.get_text(" ", strip=True),
        )[:100]

        href = anchor.get("href", "")
        onclick = anchor.get("onclick", "")

        is_pagination = bool(
            re.fullmatch(
                r"(?:\d+|next|previous|prev|last|first|»|«)",
                label,
                re.I,
            )
            or "__doPostBack" in href
            or "__doPostBack" in onclick
        )

        if not is_pagination:
            continue

        result["pagination"].append({
            "label": label,
            "href": href[:250],
            "onclick": onclick[:250],
        })

        if len(result["pagination"]) >= 25:
            break

    # 4. Job reference patterns in visible page text.
    visible = soup.get_text(" ", strip=True)

    patterns = (
        r"\b(?:Job\s*Reference|Job\s*ID|Req(?:uisition)?\s*ID)"
        r"\s*[:#-]?\s*([A-Za-z0-9_-]{4,30})",
    )

    result["job_references"] = list(
        dict.fromkeys(
            re.findall(patterns[0], visible, re.I)
        )
    )[:25]

    # 5. Script URLs only, not script contents.
    for script in soup.select("script[src]")[:40]:
        src = urljoin(
            base_url, script.get("src", "")
        )

        if urlparse(src).scheme in ("http", "https"):
            parsed = urlparse(src)

            safe_src = parsed._replace(
                query="",
                fragment="",
            ).geturl()

            result["scripts"].append(safe_src)

    # 6. Identify embedded-data mechanisms.
    html = content.lower()

    markers = {
        "ASP_NET_VIEWSTATE": "__viewstate",
        "ASP_NET_EVENTVALIDATION": "__eventvalidation",
        "NEXT_DATA": "__next_data__",
        "JSON_LD": "application/ld+json",
        "WORDPRESS_API": "wp-json",
        "GRAPHQL": "graphql",
        "JOB_POSTING": "jobposting",
        "RECRUITMENT_API": "api/jobs",
    }

    result["embedded_markers"] = [
        key
        for key, marker in markers.items()
        if marker in html
    ]

    print(
        f"[{name}] STRUCTURE "
        f"forms={len(result['forms'])} "
        f"tables={len(result['tables'])} "
        f"pagination_controls={len(result['pagination'])} "
        f"job_references={len(result['job_references'])} "
        f"script_refs={len(result['scripts'])}"
    )

    for form in result["forms"]:
        print(
            f"[{name}] FORM "
            f"method={form['method']} "
            f"action={form['action']} "
            f"fields={form['fields']!r} "
            f"hidden_names={form['hidden_names']!r}"
        )

    for table in result["tables"][:5]:
        print(
            f"[{name}] TABLE "
            f"id={table['id']!r} "
            f"headers={table['headers']!r} "
            f"rows={table['rows'][:3]!r} "
            f"html_rows={table['row_count_in_html']}"
        )

    for control in result["pagination"][:15]:
        print(
            f"[{name}] PAGE_CONTROL {control!r}"
        )

    for reference in result["job_references"][:15]:
        print(
            f"[{name}] JOB_REFERENCE {reference}"
        )

    for src in result["scripts"][:12]:
        print(f"[{name}] SCRIPT {src}")

    print(
        f"[{name}] EMBEDDED_MARKERS="
        f"{result['embedded_markers']!r}"
    )

    return result


def _company_batch_page(name, url, session):
    """Inspect a public careers page with bounded output."""
    print(f"\n[{name}] PAGE={url}")

    try:
        result = limited_get(session, url)
    except requests.RequestException as exc:
        print(
            f"[{name}] REQUEST_FAILED "
            f"{type(exc).__name__}: {exc}"
        )
        return None

    print(
        f"[{name}] status={result['status']} "
        f"final_url={result['url']} "
        f"bytes={result['bytes']} "
        f"truncated={result['truncated']}"
    )

    if (
        result["status"] != 200
        or result["truncated"]
        or classify_page(result) != "HTML"
    ):
        print(f"[{name}] INVENTORY_NOT_VERIFIED")
        return None

    soup = BeautifulSoup(
        result["content"],
        "html.parser",
    )

    structure = None

    if name in ("CRISIL", "TECHMAHINDRA"):
        structure = inspect_company_page_structure(
            name,
            result["content"],
            result["url"],
        )

    links = {}
    pagination = []
    ats_links = []

    for anchor in soup.select("a[href]"):
        href = urljoin(
            result["url"],
            anchor.get("href", ""),
        )

        parsed = urlparse(href)

        if parsed.scheme not in ("http", "https"):
            continue

        title = re.sub(
            r"\s+",
            " ",
            anchor.get_text(" ", strip=True),
        ).strip()

        if not title:
            continue

        if _COMPANY_BATCH_ROLE_RE.search(title):
            links[href] = title

        if re.search(
            r"^(?:next|[2-9]|\d{2,}|last)$",
            title,
            re.I,
        ):
            pagination.append(href)

        if any(
            marker in (parsed.hostname or "").lower()
            for marker in (
                "myworkdayjobs.com",
                "successfactors.com",
                "greenhouse.io",
                "lever.co",
                "icims.com",
                "ripplehire.com",
                "smartrecruiters.com",
            )
        ):
            ats_links.append(href)

    print(
        f"[{name}] role_link_candidates={len(links)} "
        f"pagination_links={len(set(pagination))} "
        f"ats_links={len(set(ats_links))}"
    )

    for href, title in list(links.items())[:12]:
        print(
            f"[{name}] ROLE_CANDIDATE "
            f"title={title!r} url={href}"
        )

    for href in list(dict.fromkeys(ats_links))[:8]:
        print(f"[{name}] ATS_LINK={href}")

    # Detect structured data without dumping scripts.
    scripts = soup.select("script")

    markers = (
        "__NEXT_DATA__",
        "JobPosting",
        "jobPosting",
        "requisition",
        "jobOpenings",
        "__VIEWSTATE",
        "__EVENTVALIDATION",
        "wp-json",
    )

    page_text = str(soup)

    for marker in markers:
        if marker.casefold() in page_text.casefold():
            print(
                f"[{name}] STRUCTURE_MARKER={marker}"
            )

    print(
        f"[{name}] scripts={len(scripts)} "
        f"pagination_verified=NO "
        f"authoritative_total=UNKNOWN"
    )

    return {
        "url": result["url"],
        "links": links,
        "pagination": list(
            dict.fromkeys(pagination)
        ),
        "soup": soup,
        "structure": structure,
    }


def run_company_batch():
    print("=" * 70)
    print("THREE COMPANY ATS RESEARCH - READ ONLY")
    print("=" * 70)

    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        for name, urls in COMPANY_BATCH_TARGETS.items():
            print(f"\n[{name}] RESEARCH_START")

            if name == "CLOVER":
                print(
                    "[CLOVER] SKIPPED "
                    "reason=HTTP_403_ON_ALL_OFFICIAL_SOURCES "
                    "status=UNRESOLVED"
                )
                continue

            discovered = {}
            pages = []

            for url in urls:
                page = _company_batch_page(
                    name,
                    url,
                    session,
                )

                if page is not None:
                    pages.append(page)
                    discovered.update(page["links"])

                time.sleep(DELAY_SECONDS)

            # Follow only observed same-host pagination links.
            # Never fabricate page query parameters.
            visited = {
                urldefrag(page["url"])[0]
                for page in pages
            }

            extra_pages = []

            for page in pages:
                source_host = urlparse(
                    page["url"]
                ).hostname

                for next_url in page["pagination"]:
                    normalized_url, _ = urldefrag(next_url)

                    if normalized_url in visited:
                        continue

                    if urlparse(normalized_url).hostname != source_host:
                        continue

                    visited.add(normalized_url)
                    extra_pages.append(normalized_url)

                    if len(extra_pages) >= 3:
                        break

                if len(extra_pages) >= 3:
                    break

            for url in extra_pages:
                page = _company_batch_page(
                    name,
                    url,
                    session,
                )

                if page is not None:
                    discovered.update(page["links"])

                time.sleep(DELAY_SECONDS)

            if name == "TECHMAHINDRA":
                try:
                    probe_techmahindra_navigation(
                        session
                    )
                except (
                    requests.RequestException,
                    ValueError,
                ) as exc:
                    print(
                        "[TECHMAHINDRA] "
                        "NAVIGATION_FAILED "
                        f"type={type(exc).__name__}"
                    )

            india_candidates = [
                (url, title)
                for url, title in discovered.items()
                if (
                    _COMPANY_BATCH_INDIA_RE.search(title)
                    or _COMPANY_BATCH_INDIA_RE.search(url)
                )
            ]

            print(
                f"[{name}] SUMMARY "
                f"pages_inspected={len(pages) + len(extra_pages)} "
                f"distinct_role_links={len(discovered)} "
                f"india_hints={len(india_candidates)} "
                "exhaustive_inventory=NO"
            )

            print(
                f"[{name}] DECISION=PROBE_REQUIRED "
                "unless authoritative inventory "
                "and pagination were independently verified"
            )

    finally:
        session.close()

    print("\n[COMPANY_BATCH] COMPLETE")
    print("[COMPANY_BATCH] No registry changes")
    print("[COMPANY_BATCH] No state writes")
    print("[COMPANY_BATCH] No Telegram notifications")


# ============================================================
# BrowserStack / Barclays / Zycus integration research
# ============================================================

_INTEGRATION_ROLE_RE = re.compile(
    r"java|spring|backend|back.end|full.stack|"
    r"software engineer|software developer|react|"
    r"microservices",
    re.I,
)

_INTEGRATION_INDIA_RE = re.compile(
    r"india|mumbai|navi.mumbai|bengaluru|"
    r"bangalore|hyderabad|pune|chennai|noida",
    re.I,
)


def _integration_summary(name, jobs):
    ids = [str(job.id) for job in jobs]
    urls = [str(job.url) for job in jobs]

    relevant = [
        job for job in jobs
        if (
            _INTEGRATION_ROLE_RE.search(job.title)
            and _INTEGRATION_INDIA_RE.search(
                job.location
            )
        )
    ]

    print(
        f"[{name}] normalized={len(jobs)} "
        f"unique_ids={len(set(ids))} "
        f"unique_urls={len(set(urls))} "
        f"india_tech={len(relevant)}"
    )

    for job in relevant[:10]:
        print(
            f"[{name}] INDIA_TECH "
            f"id={job.id!r} "
            f"title={job.title!r} "
            f"location={job.location!r} "
            f"url={job.url}"
        )

    return (
        bool(jobs)
        and len(ids) == len(set(ids))
        and len(urls) == len(set(urls))
    )


def _probe_existing_workday(company_id, registry):
    from src.providers.workday import WorkdayAdapter

    matches = [
        company for company in registry.companies
        if company.id == company_id
    ]

    if len(matches) != 1:
        print(
            f"[{company_id}] REGISTRY_ERROR "
            f"matches={len(matches)}"
        )
        return False

    company = matches[0].model_copy(deep=True)

    print(
        f"[{company_id}] provider="
        f"{company.provider.type.value} "
        f"enabled={company.enabled}"
    )

    if company.provider.type.value != "workday":
        print(
            f"[{company_id}] PROVIDER_CHANGED "
            "manual review required"
        )
        return False

    try:
        jobs = WorkdayAdapter().fetch_jobs(company)
    except Exception as exc:
        print(
            f"[{company_id}] WORKDAY_FAILED "
            f"{type(exc).__name__}: {exc}"
        )
        return False

    return _integration_summary(
        company_id.upper(), jobs
    )


def _probe_barclays_talentbrew(registry):
    from models.company import (
        Provider,
        ProviderConfig,
        ProviderStatus,
        ProviderType,
    )
    from src.providers.talentbrew import TalentBrewAdapter

    matches = [
        company for company in registry.companies
        if company.id == "barclays"
    ]

    if len(matches) != 1:
        print("[BARCLAYS_TB] REGISTRY_ERROR")
        return

    # Temporary configuration: never change the registry.
    company = matches[0].model_copy(deep=True)
    company.provider = Provider(
        type=ProviderType.TALENTBREW,
        status=ProviderStatus.PARTIAL,
        config=ProviderConfig(
            base_url="https://search.jobs.barclays",
            page_size=16,
        ),
    )

    adapter = TalentBrewAdapter()
    all_jobs = []

    # Validate two pages, not a full 500-page crawl.
    for page in (1, 2):
        try:
            html = adapter._fetch_html(
                "https://search.jobs.barclays/search-jobs",
                company,
                params={"p": page},
            )

            jobs = adapter._extract_jobs(
                html, company
            )

            total = adapter._extract_total(html)

            print(
                f"[BARCLAYS_TB] page={page} "
                f"parsed={len(jobs)} "
                f"reported_total={total!r}"
            )

            all_jobs.extend(jobs)

        except Exception as exc:
            print(
                f"[BARCLAYS_TB] page={page} "
                f"ERROR={type(exc).__name__}: {exc}"
            )
            return

    _integration_summary(
        "BARCLAYS_TB", all_jobs
    )

    print(
        "[BARCLAYS_TB] "
        "full_inventory=NOT_VERIFIED "
        "provider_switch=NOT_APPROVED"
    )


def _probe_zycus(session):
    sources = (
        "https://www.zycus.com/company/careers",
        "https://www.zycus.com/company/careers/india-careers",
    )

    for url in sources:
        print(f"[ZYCUS] SOURCE={url}")

        try:
            result = limited_get(session, url)
        except requests.RequestException as exc:
            print(
                f"[ZYCUS] REQUEST_FAILED "
                f"{type(exc).__name__}: {exc}"
            )
            continue

        print(
            f"[ZYCUS] status={result['status']} "
            f"final={result['url']} "
            f"bytes={result['bytes']}"
        )

        if (
            result["status"] != 200
            or result["truncated"]
            or classify_page(result) != "HTML"
        ):
            continue

        soup = BeautifulSoup(
            result["content"], "html.parser"
        )

        links = []

        for anchor in soup.select("a[href]"):
            href = urljoin(
                result["url"],
                anchor.get("href", ""),
            )

            if urlparse(href).scheme not in (
                "http", "https"
            ):
                continue

            title = anchor.get_text(
                " ", strip=True
            )

            if (
                _INTEGRATION_ROLE_RE.search(title)
                or re.search(
                    r"jobs|openings|apply|careers",
                    title + " " + href,
                    re.I,
                )
            ):
                links.append((title, href))

        print(
            f"[ZYCUS] candidate_links="
            f"{len(links)}"
        )

        for title, href in links[:15]:
            parsed = urlparse(href)
            safe_url = parsed._replace(
                query="", fragment=""
            ).geturl()

            print(
                f"[ZYCUS] LINK "
                f"title={title[:100]!r} "
                f"url={safe_url}"
            )

    print(
        "[ZYCUS] ATS=UNVERIFIED "
        "inventory=UNVERIFIED "
        "pagination=UNVERIFIED"
    )


# ============================================================
# Zycus / Talismatic public inventory validation
# Research only - no registry or state changes
# ============================================================

_ZYCUS_BOARD = "https://zycus.talismatic.com/jobs"

_ZYCUS_INDIA = (
    "https://www.zycus.com/company/careers/india-careers"
)

_TALISMATIC_HOST = "zycus.talismatic.com"

_TALISMATIC_JOB_RE = re.compile(
    r"^/jobs/([A-Za-z0-9_-]+)/?$"
)

_ZYCUS_ROLE_RE = re.compile(
    r"java|spring|backend|full[\s-]?stack|"
    r"software engineer|software developer|react",
    re.I,
)

_ZYCUS_INDIA_RE = re.compile(
    r"india|mumbai|bengaluru|bangalore|"
    r"pune|hyderabad|chennai|noida",
    re.I,
)


def _zycus_safe_url(url: str) -> str:
    """Remove query parameters and fragments from report URLs."""
    parsed = urlparse(url)

    return parsed._replace(
        query="",
        fragment="",
    ).geturl()


def _zycus_job_links(
    html: str,
    base_url: str,
) -> dict:
    """Extract public Talismatic job links from HTML."""
    soup = BeautifulSoup(html, "html.parser")

    jobs = {}

    for anchor in soup.select("a[href]"):
        absolute = urljoin(
            base_url,
            anchor["href"],
        )

        parsed = urlparse(absolute)

        if (
            parsed.scheme != "https"
            or parsed.hostname != _TALISMATIC_HOST
            or parsed.username
            or parsed.password
        ):
            continue

        match = _TALISMATIC_JOB_RE.fullmatch(
            parsed.path
        )

        if not match:
            continue

        job_id = match.group(1)

        title = " ".join(
            anchor.get_text(
                " ",
                strip=True,
            ).split()
        )

        # Deduplicate by canonical job ID.
        if job_id in jobs:
            if not jobs[job_id]["title"] and title:
                jobs[job_id]["title"] = title
            continue

        jobs[job_id] = {
            "id": job_id,
            "title": title,
            "url": _zycus_safe_url(absolute),
        }

    return jobs


def _zycus_valid_pagination_url(
    url: str,
) -> bool:
    """Allow only bounded, explicit public page navigation."""
    parsed = urlparse(url)

    if (
        parsed.scheme != "https"
        or parsed.hostname != _TALISMATIC_HOST
        or parsed.username
        or parsed.password
        or parsed.path.rstrip("/") != "/jobs"
        or parsed.fragment
    ):
        return False

    params = parse_qs(
        parsed.query,
        keep_blank_values=True,
    )

    if set(params) != {"page"}:
        return False

    values = params["page"]

    if len(values) != 1:
        return False

    if not re.fullmatch(r"[0-9]+", values[0]):
        return False

    page = int(values[0])

    return 2 <= page <= 100


def _zycus_structure(
    html: str,
    base_url: str,
) -> dict:
    """Inspect public HTML and observable inventory structure."""
    soup = BeautifulSoup(html, "html.parser")

    scripts = []

    for script in soup.select("script[src]"):
        url = urljoin(
            base_url,
            script["src"],
        )

        parsed = urlparse(url)

        if (
            parsed.scheme not in ("http", "https")
            or parsed.username
            or parsed.password
        ):
            continue

        scripts.append(_zycus_safe_url(url))

    json_ld = []

    for script in soup.select(
        'script[type="application/ld+json"]'
    ):
        try:
            value = json.loads(
                script.string or ""
            )
        except (ValueError, TypeError):
            continue

        entries = (
            value
            if isinstance(value, list)
            else [value]
        )

        for entry in entries:
            if not isinstance(entry, dict):
                continue

            json_ld.append({
                "type": entry.get("@type"),
                "has_graph": "@graph" in entry,
            })

    pagination = set()

    for anchor in soup.select("a[href]"):
        label = anchor.get_text(
            " ",
            strip=True,
        )

        if not re.fullmatch(
            r"\d+|Next|Previous|Last",
            label,
            re.IGNORECASE,
        ):
            continue

        # Preserve query parameters for actual navigation.
        url = urljoin(
            base_url,
            anchor["href"],
        )

        if _zycus_valid_pagination_url(url):
            pagination.add(url)

    return {
        "job_links": _zycus_job_links(
            html,
            base_url,
        ),
        "pagination_links": sorted(pagination),
        "scripts": list(dict.fromkeys(scripts))[:15],
        "json_ld": json_ld[:10],
        "has_next_data": "__NEXT_DATA__" in html,
        "has_nuxt_data": "__NUXT__" in html,
    }


def _zycus_public_jobposting_objects(html: str) -> list[dict]:
    """Read public JSON-LD JobPosting objects, if present."""
    soup = BeautifulSoup(html, "html.parser")
    jobs = []

    def visit(value):
        if isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            kinds = value.get("@type", [])
            if isinstance(kinds, str):
                kinds = [kinds]

            if "JobPosting" in kinds:
                jobs.append(value)

            if "@graph" in value:
                visit(value["@graph"])

    for script in soup.select(
        'script[type="application/ld+json"]'
    ):
        try:
            value = json.loads(script.string or "")
        except (TypeError, ValueError):
            continue
        visit(value)

    return jobs[:20]


def _zycus_nextjs_evidence(html: str) -> dict:
    """Inspect bounded public frontend-state evidence."""
    soup = BeautifulSoup(html, "html.parser")

    next_data = soup.select_one(
        'script#__NEXT_DATA__[type="application/json"]'
    )

    next_data_keys = []
    if next_data:
        try:
            payload = json.loads(next_data.string or "")
            if isinstance(payload, dict):
                next_data_keys = sorted(payload)[:20]
        except (TypeError, ValueError):
            pass

    flight_scripts = [
        script.get_text()
        for script in soup.select("script")
        if "self.__next_f.push" in script.get_text()
    ]

    flight_text = "\n".join(
        text[:50000] for text in flight_scripts[:20]
    )

    # Evidence only: do not treat string matches as job records.
    job_markers = {
        marker: flight_text.lower().count(marker.lower())
        for marker in (
            "jobId",
            "jobTitle",
            "jobLocation",
            "requisition",
            "pagination",
            "totalCount",
        )
    }

    return {
        "next_data_keys": next_data_keys,
        "flight_script_count": len(flight_scripts),
        "flight_bytes_inspected": len(flight_text),
        "flight_job_markers": job_markers,
        "has_jobposting_jsonld": bool(
            _zycus_public_jobposting_objects(html)
        ),
    }


def _zycus_detail_evidence(
    html: str,
    expected_job_id: str,
) -> dict:
    """Extract public detail evidence without guessing fields."""
    soup = BeautifulSoup(html, "html.parser")

    postings = _zycus_public_jobposting_objects(html)

    title = ""
    location = ""
    employment = ""

    if postings:
        posting = postings[0]

        title = str(posting.get("title") or "")
        employment = str(
            posting.get("employmentType") or ""
        )

        places = posting.get("jobLocation") or []
        if isinstance(places, dict):
            places = [places]

        location_parts = []

        for place in places:
            if not isinstance(place, dict):
                continue

            address = place.get("address")
            if not isinstance(address, dict):
                continue

            location_parts.extend(
                str(address.get(field) or "")
                for field in (
                    "addressLocality",
                    "addressRegion",
                    "addressCountry",
                )
            )

        location = ", ".join(
            part for part in location_parts if part
        )

    if not title:
        heading = soup.select_one("h1")
        if heading:
            title = heading.get_text(" ", strip=True)

    if not title and soup.title:
        title = soup.title.get_text(" ", strip=True)

    canonical = soup.select_one(
        'link[rel="canonical"][href]'
    )

    canonical_url = ""
    if canonical:
        candidate = urljoin(
            "https://zycus.talismatic.com",
            canonical["href"],
        )
        parsed = urlparse(candidate)

        if (
            parsed.scheme == "https"
            and parsed.hostname == "zycus.talismatic.com"
            and parsed.path.rstrip("/")
            == f"/jobs/{expected_job_id}"
        ):
            canonical_url = parsed._replace(
                query="",
                fragment="",
            ).geturl()

    return {
        "id": expected_job_id,
        "title": title[:150],
        "location": location[:200],
        "employment_type": employment[:100],
        "canonical": canonical_url,
        "jsonld_job_count": len(postings),
        "nextjs": _zycus_nextjs_evidence(html),
    }


def probe_zycus_talismatic(session) -> None:
    """Validate official Zycus/Talismatic public sources."""
    print("\n[ZYCUS_TALISMATIC] START")

    sources = (
        ("BOARD", _ZYCUS_BOARD),
        ("OFFICIAL_INDIA", _ZYCUS_INDIA),
    )

    inventories = {}
    board_structure = None

    for label, url in sources:
        try:
            result = limited_get(
                session,
                url,
            )
        except requests.RequestException as exc:
            print(
                f"[ZYCUS_TALISMATIC] {label} "
                f"REQUEST_FAILED={type(exc).__name__}"
            )
            continue

        print(
            f"[ZYCUS_TALISMATIC] {label} "
            f"status={result['status']} "
            f"bytes={result['bytes']} "
            f"truncated={result['truncated']}"
        )

        if (
            result["status"] != 200
            or result["truncated"]
            or classify_page(result) != "HTML"
        ):
            print(
                f"[ZYCUS_TALISMATIC] {label} "
                "INVENTORY_NOT_VERIFIED"
            )
            continue

        structure = _zycus_structure(
            result["content"],
            result["url"],
        )

        inventories[label] = structure["job_links"]

        print(
            f"[ZYCUS_TALISMATIC] {label} "
            f"unique_ids={len(structure['job_links'])} "
            f"pagination_links="
            f"{len(structure['pagination_links'])} "
            f"json_ld={len(structure['json_ld'])} "
            f"next_data={structure['has_next_data']} "
            f"nuxt_data={structure['has_nuxt_data']}"
        )

        for script in structure["scripts"][:8]:
            print(
                "[ZYCUS_TALISMATIC] SCRIPT "
                f"{script}"
            )

        for job in list(
            structure["job_links"].values()
        )[:12]:
            print(
                "[ZYCUS_TALISMATIC] JOB "
                f"id={job['id']} "
                f"title={job['title'][:100]!r} "
                f"url={job['url']}"
            )

        if label == "BOARD":
            board_structure = structure

            nextjs = _zycus_nextjs_evidence(
                result["content"]
            )

            print(
                "[ZYCUS_TALISMATIC] BOARD_NEXTJS "
                f"evidence={nextjs!r}"
            )

        time.sleep(DELAY_SECONDS)

    board_ids = set(
        inventories.get("BOARD", {})
    )

    india_ids = set(
        inventories.get("OFFICIAL_INDIA", {})
    )

    print(
        "[ZYCUS_TALISMATIC] OVERLAP "
        f"board={len(board_ids)} "
        f"india={len(india_ids)} "
        f"shared={len(board_ids & india_ids)} "
        f"missing_from_board={len(india_ids - board_ids)}"
    )

    official_jobs = inventories.get(
        "OFFICIAL_INDIA", {}
    )

    relevant = [
        job
        for job in official_jobs.values()
        if _ZYCUS_ROLE_RE.search(job["title"])
    ]

    print(
        "[ZYCUS_TALISMATIC] OFFICIAL_RELEVANCE "
        f"total_links={len(official_jobs)} "
        f"technology_title_matches={len(relevant)}"
    )

    for job in relevant[:10]:
        print(
            "[ZYCUS_TALISMATIC] ROLE_CANDIDATE "
            f"id={job['id']} "
            f"title={job['title'][:100]!r} "
            f"url={job['url']}"
        )

    # Test at most two observed pagination links.
    # Do not invent page parameters or endpoints.
    if board_structure is not None:
        visited = {_ZYCUS_BOARD}

        for page_url in board_structure[
            "pagination_links"
        ][:2]:
            if page_url in visited:
                continue

            if not _zycus_valid_pagination_url(page_url):
                print(
                    "[ZYCUS_TALISMATIC] "
                    "PAGINATION_SKIPPED"
                )
                continue

            visited.add(page_url)

            try:
                result = limited_get(
                    session,
                    page_url,
                )

                if (
                    result["status"] != 200
                    or result["truncated"]
                    or classify_page(result) != "HTML"
                ):
                    print(
                        "[ZYCUS_TALISMATIC] PAGE_FAILED "
                        f"status={result['status']}"
                    )
                    continue

                page_jobs = _zycus_job_links(
                    result["content"],
                    result["url"],
                )

                page_ids = set(page_jobs)

                print(
                    "[ZYCUS_TALISMATIC] PAGE "
                    f"jobs={len(page_ids)} "
                    f"overlap={len(board_ids & page_ids)} "
                    f"new={len(page_ids - board_ids)}"
                )

            except requests.RequestException as exc:
                print(
                    "[ZYCUS_TALISMATIC] PAGE_ERROR "
                    f"{type(exc).__name__}"
                )

            time.sleep(DELAY_SECONDS)

    # Verify only two previously observed official job URLs.
    for job_id in (
        "JLYSPUJVX",
        "JLSEKA3V3",
    ):
        url = f"{_ZYCUS_BOARD}/{job_id}"

        try:
            result = limited_get(
                session,
                url,
            )

            print(
                "[ZYCUS_TALISMATIC] DETAIL "
                f"id={job_id} "
                f"status={result['status']} "
                f"bytes={result['bytes']}"
            )

            if (
                result["status"] == 200
                and not result["truncated"]
                and classify_page(result) == "HTML"
            ):
                evidence = _zycus_detail_evidence(
                    result["content"],
                    job_id,
                )

                print(
                    "[ZYCUS_TALISMATIC] DETAIL_FIELDS "
                    f"id={job_id} "
                    f"title={evidence['title']!r} "
                    f"location={evidence['location']!r} "
                    f"employment={evidence['employment_type']!r} "
                    f"canonical={evidence['canonical']!r} "
                    f"jsonld_jobs={evidence['jsonld_job_count']}"
                )

                print(
                    "[ZYCUS_TALISMATIC] DETAIL_NEXTJS "
                    f"id={job_id} "
                    f"evidence={evidence['nextjs']!r}"
                )

        except requests.RequestException as exc:
            print(
                "[ZYCUS_TALISMATIC] DETAIL_ERROR "
                f"id={job_id} "
                f"{type(exc).__name__}"
            )

        time.sleep(DELAY_SECONDS)

    print(
        "[ZYCUS_TALISMATIC] "
        "authoritative_total=UNKNOWN "
        "exhaustive_inventory=NO "
        "adapter_compatibility=NOT_VERIFIED"
    )

    print("[ZYCUS_TALISMATIC] COMPLETE")


def run_integration_batch():
    from research.loader import load_registry

    print("=" * 70)
    print("BROWSERSTACK / BARCLAYS / ZYCUS")
    print("INTEGRATION RESEARCH - READ ONLY")
    print("=" * 70)

    registry = load_registry()

    for company_id in ("browserstack", "barclays"):
        _probe_existing_workday(
            company_id, registry
        )

    _probe_barclays_talentbrew(registry)

    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        probe_zycus_talismatic(session)
    finally:
        session.close()

    print("[INTEGRATION_BATCH] COMPLETE")
    print("[INTEGRATION_BATCH] No registry changes")
    print("[INTEGRATION_BATCH] No state writes")
    print("[INTEGRATION_BATCH] No Telegram notifications")
    print("[INTEGRATION_BATCH] No provider switching")


# ============================================================
# Mastek / LTIMindtree / KPMG
# Consolidated enterprise ATS validation
# ============================================================

_ENTERPRISE_SOURCES = {
    "MASTEK": [
        "https://www.mastek.com/careers/",
        "https://careers.mastek.com/search/",
    ],
    "LTIMINDTREE": [
        "https://careers.ltm.com/search/",
        "https://www.ltm.com/india-careers",
    ],
    "KPMG": [
        "https://kpmg.com/in/en/careers.html",
    ],
}

_ENTERPRISE_ROLE_RE = re.compile(
    r"java|spring|backend|back[\s-]?end|"
    r"full[\s-]?stack|react|microservices|"
    r"software engineer|software developer",
    re.I,
)

_ENTERPRISE_INDIA_RE = re.compile(
    r"india|mumbai|navi.mumbai|bengaluru|"
    r"bangalore|pune|hyderabad|chennai|noida",
    re.I,
)

_ENTERPRISE_ATS_HOSTS = (
    "oraclecloud.com",
    "ripplehire.com",
    "talentrecruit.com",
    "successfactors.com",
    "jobs2web.com",
)


def _enterprise_safe_url(value):
    parsed = urlparse(value)
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        return None

    return parsed._replace(
        query="", fragment=""
    ).geturl()


def _enterprise_page_evidence(html, base_url):
    """Extract bounded public recruitment evidence."""
    soup = BeautifulSoup(html, "html.parser")

    job_links = {}
    ats_links = set()
    pagination = set()

    for anchor in soup.select("a[href]"):
        raw_url = urljoin(
            base_url, anchor["href"]
        )
        safe_url = _enterprise_safe_url(raw_url)

        if not safe_url:
            continue

        parsed = urlparse(safe_url)

        title = " ".join(
            anchor.get_text(" ", strip=True).split()
        )

        if any(
            host in (parsed.hostname or "")
            for host in _ENTERPRISE_ATS_HOSTS
        ):
            ats_links.add(safe_url)

        if (
            _ENTERPRISE_ROLE_RE.search(title)
            and (
                "/job/" in parsed.path
                or "/jobs/" in parsed.path
            )
        ):
            job_links[safe_url] = title[:120]

        if re.fullmatch(
            r"\d+|next|previous|last",
            title, re.I
        ):
            pagination.add(safe_url)

    oracle_sites = set()

    for link in ats_links:
        parsed = urlparse(link)
        match = re.search(
            r"/sites/([^/?#]+)",
            parsed.path,
            re.I,
        )
        if (
            match
            and "oraclecloud.com"
            in (parsed.hostname or "")
        ):
            oracle_sites.add(
                (
                    parsed.hostname,
                    match.group(1),
                )
            )

    return {
        "job_links": job_links,
        "ats_links": sorted(ats_links),
        "pagination": sorted(pagination),
        "oracle_sites": sorted(oracle_sites),
        "forms": len(soup.select("form")),
        "scripts": len(soup.select("script")),
    }


def _enterprise_inspect_sources(session, name, urls):
    """Inspect official sources without changing registry state."""
    print(f"\n[{name}] SOURCE_DISCOVERY")

    for url in urls:
        try:
            result = limited_get(session, url)
        except requests.RequestException as exc:
            print(
                f"[{name}] REQUEST_FAILED "
                f"type={type(exc).__name__}"
            )
            continue

        print(
            f"[{name}] SOURCE "
            f"status={result['status']} "
            f"bytes={result['bytes']} "
            f"truncated={result['truncated']}"
        )

        if (
            result["status"] != 200
            or result["truncated"]
            or classify_page(result) != "HTML"
        ):
            print(f"[{name}] PARSE_NOT_VERIFIED")
            continue

        evidence = _enterprise_page_evidence(
            result["content"],
            result["url"],
        )

        print(
            f"[{name}] STRUCTURE "
            f"job_links={len(evidence['job_links'])} "
            f"ats_links={len(evidence['ats_links'])} "
            f"pagination_links={len(evidence['pagination'])} "
            f"forms={evidence['forms']} "
            f"scripts={evidence['scripts']}"
        )

        for link in evidence["ats_links"][:12]:
            print(f"[{name}] ATS_LINK={link}")

        for host, site_path in evidence[
            "oracle_sites"
        ]:
            print(
                f"[{name}] ORACLE_SITE "
                f"host={host} site_path={site_path} "
                "site_number=UNVERIFIED"
            )

        for link, title in list(
            evidence["job_links"].items()
        )[:10]:
            print(
                f"[{name}] JOB_CANDIDATE "
                f"title={title!r} url={link}"
            )

        time.sleep(DELAY_SECONDS)


def _enterprise_validate_existing(company_id, registry):
    """Validate an existing SuccessFactors mapping."""
    from src.providers.successfactors import (
        SuccessFactorsAdapter,
    )

    matches = [
        company for company in registry.companies
        if company.id == company_id
    ]

    if len(matches) != 1:
        print(
            f"[{company_id}] REGISTRY_MATCHES={len(matches)}"
        )
        return False

    company = matches[0].model_copy(deep=True)

    if company.provider.type.value != "successfactors":
        print(
            f"[{company_id}] PROVIDER_MISMATCH="
            f"{company.provider.type.value}"
        )
        return False

    try:
        jobs = SuccessFactorsAdapter().fetch_jobs(
            company
        )
    except Exception as exc:
        print(
            f"[{company_id}] ADAPTER_FAILED "
            f"type={type(exc).__name__}"
        )
        return False

    ids = [str(job.id) for job in jobs]
    urls = [str(job.url) for job in jobs]

    relevant = [
        job for job in jobs
        if (
            _ENTERPRISE_ROLE_RE.search(job.title)
            and _ENTERPRISE_INDIA_RE.search(
                job.location
            )
        )
    ]

    print(
        f"[{company_id}] ADAPTER "
        f"normalized={len(jobs)} "
        f"unique_ids={len(set(ids))} "
        f"unique_urls={len(set(urls))} "
        f"india_tech={len(relevant)}"
    )

    for job in relevant[:10]:
        print(
            f"[{company_id}] INDIA_TECH "
            f"title={job.title!r} "
            f"location={job.location!r} "
            f"url={job.url}"
        )

    return (
        bool(jobs)
        and len(ids) == len(set(ids))
        and len(urls) == len(set(urls))
    )


# ============================================================
# Mastek SuccessFactors validation
# ============================================================

_MASTEK_BASE = "https://careers.mastek.com"
_MASTEK_SEARCH = f"{_MASTEK_BASE}/search/"

_MASTEK_JOB_ID_RE = re.compile(
    r"/job/[^?#]+?/(\d+)/?$",
    re.I,
)


def _mastek_listing_evidence(html: str, base_url: str) -> dict:
    """Extract listing links and observed pagination."""
    from src.providers.successfactors import SuccessFactorsAdapter

    adapter = SuccessFactorsAdapter()
    soup = BeautifulSoup(html, "html.parser")

    job_urls = adapter._extract_job_urls(
        html,
        _MASTEK_BASE,
    )

    jobs = {}
    for url in job_urls:
        parsed = urlparse(url)
        if parsed.hostname != "careers.mastek.com":
            continue

        match = _MASTEK_JOB_ID_RE.search(parsed.path)
        if match:
            jobs[match.group(1)] = url

    pagination = set()

    for anchor in soup.select("a[href]"):
        label = anchor.get_text(" ", strip=True)
        href = urljoin(base_url, anchor["href"])
        parsed = urlparse(href)

        if (
            parsed.scheme != "https"
            or parsed.hostname != "careers.mastek.com"
        ):
            continue

        is_pager = bool(
            re.fullmatch(
                r"\d+|next|previous|last",
                label,
                re.I,
            )
            or re.search(
                r"(?:startrow|/search/\d+/)",
                href,
                re.I,
            )
        )

        if is_pager:
            pagination.add(href)

    return {
        "jobs": jobs,
        "pagination": sorted(pagination),
    }


def _mastek_pagination_structure(html: str) -> dict:
    """Inspect actual RMK pagination and listing structure."""
    soup = BeautifulSoup(html, "html.parser")

    forms = []
    for form in soup.select("form")[:8]:
        controls = []

        for control in form.select(
            "input[name], button[name], select[name]"
        )[:40]:
            controls.append({
                "tag": control.name,
                "name": control.get("name", "")[:100],
                "type": control.get("type", "")[:30],
            })

        forms.append({
            "id": form.get("id", "")[:100],
            "method": form.get("method", "get").upper(),
            "controls": controls,
        })

    controls = []
    for element in soup.select(
        "a, button, [role='button'], [data-page]"
    )[:500]:
        label = " ".join(
            element.get_text(" ", strip=True).split()
        )[:70]

        attrs = {}
        for key in (
            "id", "class", "aria-label",
            "data-page", "data-startrow",
            "data-offset", "rel"
        ):
            value = element.get(key)
            if value is not None:
                attrs[key] = value

        href = element.get("href", "")
        onclick = element.get("onclick", "")

        is_pager = bool(
            re.search(
                r"next|previous|pagination|pager|"
                r"page\s*\d+|startrow|offset",
                label + " " + str(attrs),
                re.I,
            )
            or re.fullmatch(r"\d{1,3}", label)
            or "startrow" in href.lower()
            or "startrow" in onclick.lower()
        )

        if is_pager:
            controls.append({
                "label": label,
                "attributes": attrs,
                "has_href": bool(href),
                "has_onclick": bool(onclick),
            })

        if len(controls) >= 30:
            break

    text = soup.get_text(" ", strip=True)

    totals = []
    for pattern in (
        r"\b(\d+)\s+jobs?\s+found\b",
        r"\bshowing\s+\d+\s*[-–]\s*\d+"
        r"\s+of\s+(\d+)\b",
        r"\b(\d+)\s+open\s+positions\b",
        r"\btotal\s+jobs?\s*:?\s*(\d+)\b",
    ):
        totals.extend(
            re.findall(pattern, text, re.I)[:5]
        )

    markers = {
        "pagination": bool(
            re.search(r"pagination|pager", html, re.I)
        ),
        "startrow": "startrow" in html.lower(),
        "load_more": bool(
            re.search(r"load.more|show.more", html, re.I)
        ),
        "jobs2web": "jobs2web" in html.lower(),
    }

    return {
        "forms": forms,
        "controls": controls,
        "total_candidates": list(
            dict.fromkeys(totals)
        )[:10],
        "markers": markers,
    }


def probe_mastek_successfactors(session) -> None:
    """Validate official Mastek listing and one observed next page."""
    print("\n[MASTEK_SF] START")

    try:
        result = limited_get(session, _MASTEK_SEARCH)
    except requests.RequestException as exc:
        print(
            "[MASTEK_SF] LISTING_FAILED "
            f"type={type(exc).__name__}"
        )
        return

    if (
        result["status"] != 200
        or result["truncated"]
        or classify_page(result) != "HTML"
    ):
        print("[MASTEK_SF] LISTING_NOT_VERIFIED")
        return

    first = _mastek_listing_evidence(
        result["content"],
        result["url"],
    )

    structure = _mastek_pagination_structure(
        result["content"]
    )

    print(
        "[MASTEK_SF] STRUCTURE "
        f"forms={len(structure['forms'])} "
        f"pager_controls={len(structure['controls'])} "
        f"total_candidates={structure['total_candidates']} "
        f"markers={structure['markers']}"
    )

    for form in structure["forms"][:4]:
        print(f"[MASTEK_SF] FORM {form!r}")

    for control in structure["controls"][:15]:
        print(
            f"[MASTEK_SF] PAGER_CONTROL "
            f"{control!r}"
        )

    first_ids = set(first["jobs"])

    print(
        "[MASTEK_SF] PAGE_1 "
        f"jobs={len(first_ids)} "
        f"pagination_candidates={len(first['pagination'])}"
    )

    for job_id, url in list(first["jobs"].items())[:8]:
        safe_url = urlparse(url)._replace(
            query="",
            fragment="",
        ).geturl()
        print(
            f"[MASTEK_SF] JOB id={job_id} url={safe_url}"
        )

    # Follow only a next-page URL observed in the actual HTML.
    # Do not invent pagination parameters.
    candidates = []

    for url in first["pagination"]:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)

        # Supported RMK pagination patterns.
        path_match = re.fullmatch(
            r"/search/(\d+)/?",
            parsed.path,
        )

        if path_match:
            offset = int(path_match.group(1))
            mode = "path"
            parameter = None

        elif (
            parsed.path.rstrip("/") == "/search"
            and len(params.get("startrow", [])) == 1
            and params["startrow"][0].isdigit()
            and set(params) == {"startrow"}
        ):
            offset = int(params["startrow"][0])
            mode = "query"
            parameter = "startrow"

        else:
            continue

        if offset <= 0 or offset > 1000:
            continue

        candidates.append(
            (offset, mode, parameter, url)
        )

    if not candidates:
        print(
            "[MASTEK_SF] PAGINATION=UNVERIFIED "
            "reason=NO_SUPPORTED_OBSERVED_NEXT_PAGE"
        )
        return

    offset, mode, parameter, next_url = min(
        candidates,
        key=lambda item: item[0],
    )

    try:
        second_result = limited_get(session, next_url)
    except requests.RequestException as exc:
        print(
            "[MASTEK_SF] PAGE_2_FAILED "
            f"type={type(exc).__name__}"
        )
        return

    if (
        second_result["status"] != 200
        or second_result["truncated"]
        or classify_page(second_result) != "HTML"
    ):
        print("[MASTEK_SF] PAGE_2_NOT_VERIFIED")
        return

    second = _mastek_listing_evidence(
        second_result["content"],
        second_result["url"],
    )

    second_ids = set(second["jobs"])

    print(
        "[MASTEK_SF] PAGINATION "
        f"mode={mode} "
        f"parameter={parameter or 'none'} "
        f"offset={offset} "
        f"page1={len(first_ids)} "
        f"page2={len(second_ids)} "
        f"overlap={len(first_ids & second_ids)} "
        f"new={len(second_ids - first_ids)}"
    )

    if second_ids - first_ids:
        print(
            "[MASTEK_SF] PAGINATION_DISTINCT=YES "
            "full_inventory=NOT_YET_VERIFIED"
        )
    else:
        print(
            "[MASTEK_SF] PAGINATION_DISTINCT=NO "
            "adapter_activation=BLOCKED"
        )


# ============================================================
# KPMG Oracle Recruiting Cloud site discovery
# ============================================================

_KPMG_ORACLE_HOST = "ejgk.fa.em2.oraclecloud.com"

_KPMG_ORACLE_SITES = {
    "KGS": "CX_3",
    "KDN": "CX_3001",
}


def _kpmg_oracle_evidence(html: str) -> dict:
    """Find bounded public Oracle configuration evidence."""
    soup = BeautifulSoup(html, "html.parser")

    scripts = []
    for script in soup.select("script[src]")[:50]:
        src = script.get("src", "")
        if src:
            scripts.append(src.split("?", 1)[0][:200])

    # Inspect only short context around public configuration keys.
    # A CX_* site path is not a site number.
    candidates = []

    patterns = (
        r'["\']siteNumber["\']\s*:\s*["\']?(\d+)',
        r'["\']site_number["\']\s*:\s*["\']?(\d+)',
        r'\bsiteNumber\s*=\s*["\']?(\d+)',
    )

    for pattern in patterns:
        for match in re.finditer(
            pattern,
            html,
            re.I,
        ):
            candidates.append(match.group(1))

    return {
        "site_number_candidates": sorted(set(candidates)),
        "script_count": len(scripts),
        "oracle_markers": {
            "candidate_experience": (
                "CandidateExperience" in html
            ),
            "recruiting_api": (
                "recruitingCEJobRequisitions" in html
            ),
            "site_number_key": (
                "siteNumber" in html
            ),
        },
    }


def _kpmg_oracle_config_structure(
    html: str,
    base_url: str,
) -> dict:
    """Inspect public Oracle configuration references safely."""
    soup = BeautifulSoup(html, "html.parser")

    scripts = []
    for script in soup.select("script[src]")[:30]:
        absolute = urljoin(
            base_url,
            script.get("src", ""),
        )

        parsed = urlparse(absolute)

        if (
            parsed.scheme != "https"
            or parsed.hostname
            != "ejgk.fa.em2.oraclecloud.com"
            or parsed.username
            or parsed.password
        ):
            continue

        scripts.append(
            parsed._replace(
                query="",
                fragment="",
            ).geturl()
        )

    inline_markers = []

    for script in soup.select("script:not([src])")[:20]:
        content = script.get_text()

        if len(content) > 100_000:
            content = content[:100_000]

        for marker in (
            "siteNumber",
            "siteId",
            "siteCode",
            "siteName",
            "CandidateExperience",
            "recruitingCEJobRequisitions",
            "config",
        ):
            if marker.lower() in content.lower():
                inline_markers.append(marker)

    return {
        "scripts": list(dict.fromkeys(scripts))[:12],
        "inline_markers": sorted(set(inline_markers)),
        "site_number_candidates": (
            _kpmg_oracle_evidence(html)[
                "site_number_candidates"
            ]
        ),
        "forms": len(soup.select("form")),
    }


def _kpmg_inspect_public_scripts(
    session,
    scripts: list[str],
    unit: str,
) -> None:
    """Inspect at most two page-referenced public scripts."""
    for script_url in scripts[:2]:
        parsed = urlparse(script_url)

        if (
            parsed.scheme != "https"
            or parsed.hostname
            != "ejgk.fa.em2.oraclecloud.com"
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            continue

        try:
            result = limited_get(
                session,
                script_url,
            )
        except requests.RequestException as exc:
            print(
                f"[KPMG_{unit}] SCRIPT_FAILED "
                f"type={type(exc).__name__}"
            )
            continue

        if (
            result["status"] != 200
            or result["truncated"]
        ):
            print(
                f"[KPMG_{unit}] SCRIPT_UNAVAILABLE "
                f"status={result['status']}"
            )
            continue

        final_url = urlparse(result["url"])

        if (
            final_url.scheme != "https"
            or final_url.hostname
            != "ejgk.fa.em2.oraclecloud.com"
        ):
            print(
                f"[KPMG_{unit}] "
                "SCRIPT_REDIRECTED_OUTSIDE_ALLOWED_HOST"
            )
            continue

        content = result["content"]
        if isinstance(content, bytes):
            content = content.decode(
                "utf-8", errors="replace"
            )

        response_text = content.lstrip().lower()

        if response_text.startswith(
            ("<!doctype html", "<html")
        ):
            print(
                f"[KPMG_{unit}] "
                "SCRIPT_RETURNED_HTML"
            )
            continue

        evidence = _kpmg_oracle_evidence(content)

        print(
            f"[KPMG_{unit}] SCRIPT_EVIDENCE "
            f"site_number_candidates="
            f"{evidence['site_number_candidates']} "
            f"site_number_marker="
            f"{evidence['oracle_markers']['site_number_key']}"
        )

        time.sleep(DELAY_SECONDS)


def probe_kpmg_oracle_sites(session) -> None:
    """Inspect KGS/KDN official public Oracle site pages."""
    print("\n[KPMG_ORACLE] START")

    for unit, site_path in _KPMG_ORACLE_SITES.items():
        url = (
            f"https://{_KPMG_ORACLE_HOST}/"
            "hcmUI/CandidateExperience/en/sites/"
            f"{site_path}"
        )

        try:
            result = limited_get(session, url)
        except requests.RequestException as exc:
            print(
                f"[KPMG_{unit}] REQUEST_FAILED "
                f"type={type(exc).__name__}"
            )
            continue

        print(
            f"[KPMG_{unit}] SOURCE "
            f"status={result['status']} "
            f"bytes={result['bytes']} "
            f"truncated={result['truncated']}"
        )

        if (
            result["status"] != 200
            or result["truncated"]
            or classify_page(result) != "HTML"
        ):
            print(
                f"[KPMG_{unit}] SITE_NUMBER=UNVERIFIED"
            )
            continue

        evidence = _kpmg_oracle_evidence(
            result["content"]
        )

        structure = _kpmg_oracle_config_structure(
            result["content"],
            result["url"],
        )

        print(
            f"[KPMG_{unit}] CONFIG_EVIDENCE "
            f"site_path={site_path} "
            f"number_candidates="
            f"{evidence['site_number_candidates']} "
            f"scripts={evidence['script_count']} "
            f"markers={evidence['oracle_markers']}"
        )

        print(
            f"[KPMG_{unit}] PUBLIC_CONFIG "
            f"scripts={len(structure['scripts'])} "
            f"inline_markers={structure['inline_markers']} "
            f"forms={structure['forms']}"
        )

        _kpmg_inspect_public_scripts(
            session,
            structure["scripts"],
            unit,
        )

        # A string match is a candidate, not sufficient proof
        # that the number belongs to this particular site.
        print(
            f"[KPMG_{unit}] "
            "SITE_NUMBER=REQUIRES_ASSOCIATION_VALIDATION "
            "ORACLE_ADAPTER=NOT_YET_VALIDATED"
        )

        time.sleep(DELAY_SECONDS)

    print(
        "[KPMG_ORACLE] KI_TALENTRECRUIT=SEPARATE_SOURCE"
    )
    print("[KPMG_ORACLE] COMPLETE")


def run_enterprise_batch():
    from research.loader import load_registry

    print("=" * 70)
    print("MASTEK / LTIMINDTREE / KPMG")
    print("ENTERPRISE ATS RESEARCH - READ ONLY")
    print("=" * 70)

    registry = load_registry()

    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        for name, urls in _ENTERPRISE_SOURCES.items():
            _enterprise_inspect_sources(
                session, name, urls
            )

        _enterprise_validate_existing(
            "ltmindtree", registry
        )

        probe_mastek_successfactors(session)

        probe_kpmg_oracle_sites(session)
    finally:
        session.close()

    print("[MASTEK] ADAPTER=NOT_YET_VALIDATED")
    print("[LTIMINDTREE] RIPPLEHIRE_COVERAGE=UNVERIFIED")
    print("[KPMG] ORACLE_SITE_NUMBERS=UNVERIFIED")
    print("[KPMG] ORACLE_ADAPTER=NOT_YET_VALIDATED")
    print("[ENTERPRISE_BATCH] COMPLETE")
    print("[ENTERPRISE_BATCH] No registry changes")
    print("[ENTERPRISE_BATCH] No state writes")
    print("[ENTERPRISE_BATCH] No Telegram notifications")


# ============================================================
# WORKDAY HEALTH
# Small, read-only Workday diagnostics.  This deliberately does not use
# WorkdayAdapter.fetch_jobs(): that method paginates the inventory and enriches
# every ambiguous location.
# ============================================================

WORKDAY_HEALTH_TIMEOUT = (5, 15)
WORKDAY_HEALTH_BUDGET_SECONDS = 90
WORKDAY_HEALTH_DELAY_SECONDS = 0.2
WORKDAY_HEALTH_MAX_BODY_BYTES = 2_000_000
WORKDAY_HEALTH_PREVIEW_BYTES = 300
WORKDAY_HEALTH_ACCESS_MARKERS = (
    "captcha",
    "access denied",
    "verify you are human",
    "cloudflare challenge",
    "security challenge",
)


def _workday_health_boards(company):
    config = company.provider.config
    boards = list(config.boards)
    if not boards and config.board:
        boards = [config.board]
    return boards


def _workday_health_url(company, board):
    config = company.provider.config
    base = (
        f"https://{config.tenant}.{config.cluster}.myworkdayjobs.com"
    )
    return f"{base}/wday/cxs/{config.tenant}/{board}/jobs"


def _workday_health_headers(company, board):
    config = company.provider.config
    base = (
        f"https://{config.tenant}.{config.cluster}.myworkdayjobs.com"
    )
    return {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Origin": base,
        "Referer": f"{base}/en-US/{board}",
    }


def _workday_health_preview(body):
    return re.sub(r"\s+", " ", body)[:WORKDAY_HEALTH_PREVIEW_BYTES]


def _workday_health_evidence(response, body, parsed, error=None, byte_length=None):
    content_type = response.headers.get("Content-Type", "")
    evidence = {
        "status": response.status_code,
        "final_url": response.url,
        "redirects": [
            {
                "status": item.status_code,
                "location": item.headers.get("Location", ""),
            }
            for item in response.history
        ],
        "content_type": content_type,
        "bytes": len(body) if byte_length is None else byte_length,
        "retry_after": response.headers.get("Retry-After"),
        "json": "valid" if parsed is not None else "not-json",
        "top_level_keys": (
            sorted(parsed.keys()) if isinstance(parsed, dict) else []
        ),
    }
    if parsed is None:
        evidence["preview"] = _workday_health_preview(body)
    if error is not None:
        evidence["error"] = f"{type(error).__name__}: {error}"
    from src.providers.workday import WorkdayAdapter
    if WorkdayAdapter._is_maintenance_response(response):
        evidence["classification"] = "TEMPORARY_MAINTENANCE"
    return evidence


def _workday_health_response(response):
    content = response.content
    raw = content[:WORKDAY_HEALTH_MAX_BODY_BYTES]
    encoding = response.encoding or "utf-8"
    body = raw.decode(encoding, errors="replace")
    parsed = None
    error = None
    if body:
        try:
            parsed = json.loads(body)
        except (TypeError, ValueError) as exc:
            error = exc
    else:
        error = ValueError("empty response body")
    return _workday_health_evidence(
        response, body, parsed, error, byte_length=len(content)
    ), parsed


def _workday_health_print_evidence(prefix, evidence):
    redirect_chain = ";".join(
        f"{item['status']}->{item['location']}"
        for item in evidence["redirects"]
    ) or "none"
    line = (
        f"{prefix} status={evidence['status']} "
        f"final_url={evidence['final_url']} "
        f"redirects={redirect_chain} "
        f"content_type={evidence['content_type']!r} "
        f"bytes={evidence['bytes']} "
        f"retry_after={evidence['retry_after']!r} "
        f"json={evidence['json']} "
        f"top_level_keys={evidence['top_level_keys']}"
    )
    if "classification" in evidence:
        line += f" classification={evidence['classification']}"
    if "preview" in evidence:
        line += f" preview={evidence['preview']!r}"
    if "error" in evidence:
        line += f" error={evidence['error']}"
    print(line)


def _workday_health_request(session, method, url, **kwargs):
    response = getattr(session, method)(url, **kwargs)
    evidence, parsed = _workday_health_response(response)
    return response, evidence, parsed


def _workday_health_should_stop_host(response, evidence):
    if response.status_code in (403, 429):
        return True
    preview = evidence.get("preview", "").casefold()
    return any(marker in preview for marker in WORKDAY_HEALTH_ACCESS_MARKERS)


def _workday_health_detail_candidates(postings):
    from src.providers.workday import (
        _AMBIGUOUS_LOCATION_RE,
        _SINGLE_LOCATION_CODE_RE,
    )

    candidates = []
    for posting in postings:
        location = str(posting.get("locationsText") or "").strip()
        if (
            _AMBIGUOUS_LOCATION_RE.fullmatch(location)
            or _SINGLE_LOCATION_CODE_RE.match(location)
        ):
            candidates.append(posting)
        if len(candidates) == 3:
            break
    return candidates


def _workday_health_detail_url(company, board, posting):
    config = company.provider.config
    base = (
        f"https://{config.tenant}.{config.cluster}.myworkdayjobs.com"
    )
    return (
        f"{base}/wday/cxs/{config.tenant}/{board}"
        f"{posting['externalPath']}"
    )


def _workday_health_remaining(summary, reason):
    summary.append({"status": "NOT_RUN", "reason": reason})


def run_workday_health(*, session=None, budget_seconds=WORKDAY_HEALTH_BUDGET_SECONDS):
    """Run bounded, sequential Workday listing/detail diagnostics."""
    from research.loader import load_registry
    from src.providers.workday import WorkdayAdapter
    from models.company import ProviderType

    started_at = time.time()
    deadline = time.monotonic() + budget_seconds
    registry = load_registry()
    session = session or requests.Session()
    blocked_hosts = set()
    summaries = []
    adapter = WorkdayAdapter()

    print("WORKDAY_HEALTH READ_ONLY=YES")
    print(f"commit_sha={_git_commit_sha()} python={sys.version.split()[0]}")
    print(f"utc_start={time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(started_at))}")

    companies = [
        company for company in registry.companies
        if company.enabled and company.provider.type == ProviderType.WORKDAY
    ]

    for company in companies:
        boards = _workday_health_boards(company)
        for board in boards:
            key = f"{company.id}/{board}"
            summary = {"company": company.id, "board": board, "status": "OK"}
            summaries.append(summary)
            url = _workday_health_url(company, board)
            host = urlparse(url).netloc
            postings = []
            first = None
            pagination_state = "single_page"
            for offset in (0, 20):
                if time.monotonic() >= deadline:
                    _workday_health_remaining(summary.setdefault("checks", []), "overall budget exhausted")
                    break
                if host in blocked_hosts:
                    _workday_health_remaining(summary.setdefault("checks", []), "host stopped after access restriction/challenge")
                    break
                if offset == 20 and not (
                    isinstance(first, dict)
                    and isinstance(first.get("jobPostings"), list)
                    and isinstance(first.get("total"), int)
                    and first["total"] > 20
                ):
                    break
                if offset:
                    time.sleep(WORKDAY_HEALTH_DELAY_SECONDS)
                try:
                    response, evidence, data = _workday_health_request(
                        session, "post",
                        url,
                        json={
                            "appliedFacets": {}, "limit": 20,
                            "offset": offset, "searchText": "",
                        },
                        headers=_workday_health_headers(company, board),
                        timeout=WORKDAY_HEALTH_TIMEOUT,
                        allow_redirects=True,
                    )
                    _workday_health_print_evidence(
                        f"[{key}] listing method=POST requested_url={url} offset={offset}",
                        evidence,
                    )
                except Exception as exc:
                    print(
                        f"[{key}] listing method=POST requested_url={url} "
                        f"error={type(exc).__name__}: {exc}"
                    )
                    summary["status"] = (
                        "TEMPORARY_MAINTENANCE"
                        if "TEMPORARY_MAINTENANCE" in str(exc)
                        else "HTTP_FAILURE"
                    )
                    if offset:
                        pagination_state = "INCOMPLETE"
                    break
                if evidence.get("classification") == "TEMPORARY_MAINTENANCE":
                    summary["status"] = "TEMPORARY_MAINTENANCE"
                    if offset:
                        pagination_state = "INCOMPLETE"
                    break
                if _workday_health_should_stop_host(response, evidence):
                    blocked_hosts.add(host)
                if response.status_code >= 400 or not isinstance(data, dict):
                    summary["status"] = "HTTP_FAILURE" if response.status_code >= 400 else "MALFORMED_OR_EMPTY"
                    if offset:
                        pagination_state = "INCOMPLETE"
                    break
                if offset == 0:
                    first = data
                page = data.get("jobPostings")
                if not isinstance(page, list):
                    summary["status"] = "MALFORMED_OR_EMPTY"
                    if offset:
                        pagination_state = "INCOMPLETE"
                    break
                postings.extend(page)
                if offset:
                    pagination_state = "offset20_requested"

            if first is None:
                continue
            total = first.get("total")
            paths = [p.get("externalPath") for p in postings if isinstance(p, dict) and p.get("externalPath")]
            distinct = set(paths)
            print(
                f"[{key}] observed_listing_count={len(postings)} "
                f"reported_total={total!r} pagination_evidence={pagination_state} "
                f"overlapping_externalPath={len(paths)-len(distinct)} "
                f"distinct_externalPath={len(distinct)} exhaustive_inventory=NO"
            )

            candidates = _workday_health_detail_candidates(postings)
            if company.id != "salesforce":
                continue
            if not candidates:
                print(f"[{key}] salesforce_detail=NOT_SAMPLED")
                continue
            for posting in candidates:
                if time.monotonic() >= deadline or host in blocked_hosts:
                    _workday_health_remaining(summary.setdefault("checks", []), "budget or host limit")
                    break
                detail_url = _workday_health_detail_url(company, board, posting)
                base = f"https://{company.provider.config.tenant}.{company.provider.config.cluster}.myworkdayjobs.com"
                try:
                    response, evidence, data = _workday_health_request(
                        session, "get", detail_url,
                        headers={"Accept": "application/json", "Referer": f"{base}/en-US/{board}"},
                        timeout=WORKDAY_HEALTH_TIMEOUT,
                        allow_redirects=True,
                    )
                    _workday_health_print_evidence(
                        f"[{key}] detail method=GET requested_url={detail_url}", evidence
                    )
                    resolved = (
                        adapter._locations_from_detail(data)
                        if isinstance(data, dict) else None
                    )
                    print(f"[{key}] detail externalPath={posting.get('externalPath')} locations_resolved={bool(resolved)}")
                    if response.status_code >= 400:
                        summary["status"] = "HTTP_FAILURE"
                    elif not isinstance(data, dict):
                        summary["status"] = "MALFORMED_OR_EMPTY"
                    if _workday_health_should_stop_host(response, evidence):
                        blocked_hosts.add(host)
                except Exception as exc:
                    summary["status"] = "HTTP_FAILURE"
                    print(f"[{key}] detail method=GET requested_url={detail_url} error={type(exc).__name__}: {exc}")

    print("WORKDAY_HEALTH SUMMARY")
    for summary in summaries:
        print(f"[{summary['company']}/{summary['board']}] summary_status={summary['status']} checks={summary.get('checks', [])}")
    print("exhaustive_inventory=NO")


def _git_commit_sha():
    try:
        import subprocess
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return "UNKNOWN"


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Job Hunter Bot ATS research probes"
    )

    parser.add_argument(
        "--stale-recovery",
        action="store_true",
        help="Probe Postman, Atlassian, CoinDCX and Zepto",
    )
    parser.add_argument(
        "--new-companies",
        action="store_true",
        help="Probe Duck Creek, Baker Hughes and Mphasis",
    )
    parser.add_argument(
        "--activation-check",
        action="store_true",
        help="Check Duck Creek and Baker Hughes activation readiness",
    )
    parser.add_argument(
        "--company-batch",
        action="store_true",
        help="Research CRISIL, Clover Infotech and Tech Mahindra",
    )
    parser.add_argument(
        "--integration-batch",
        action="store_true",
        help="Validate BrowserStack, Barclays and Zycus",
    )
    parser.add_argument(
        "--enterprise-batch",
        action="store_true",
        help="Research Mastek, LTIMindtree and KPMG",
    )
    parser.add_argument(
        "--workday-health",
        action="store_true",
        help="Run bounded, read-only diagnostics for enabled Workday companies",
    )

    args = parser.parse_args()

    if args.workday_health:
        run_workday_health()
    elif args.enterprise_batch:
        run_enterprise_batch()
    elif args.integration_batch:
        run_integration_batch()
    elif args.company_batch:
        run_company_batch()
    elif args.activation_check:
        run_activation_check()
    elif args.new_companies:
        run_new_companies()
    elif args.stale_recovery:
        run_stale_recovery()
    else:
        main()
