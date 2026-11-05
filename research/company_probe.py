
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
import time
from collections import Counter
from html import unescape
from urllib.parse import urljoin, urlparse

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


def run_new_companies():
    print("=" * 70)
    print("NEW COMPANY ATS RESEARCH - READ ONLY")
    print("=" * 70)

    session = requests.Session()
    session.headers.update(HEADERS)

    # Validate Workday candidate endpoints.
    for name, config in NEW_COMPANY_SOURCES.items():
        probe_new_workday(name, config, session)
        time.sleep(DELAY_SECONDS)

    # Inspect official careers and recruitment pages.
    for name, url in NEW_COMPANY_PAGES.items():
        probe_new_company_page(name, url, session)
        time.sleep(DELAY_SECONDS)

    print("\n[NEW_COMPANIES] COMPLETE")
    print("[NEW_COMPANIES] No registry changes")
    print("[NEW_COMPANIES] No state writes")
    print("[NEW_COMPANIES] No Telegram notifications")
    print("[NEW_COMPANIES] No automatic ATS activation")


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

    args = parser.parse_args()

    if args.new_companies:
        run_new_companies()
    elif args.stale_recovery:
        run_stale_recovery()
    else:
        main()
