
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
    base = (
        f"https://{POSTMAN_TENANT}."
        f"{POSTMAN_CLUSTER}.myworkdayjobs.com"
    )

    endpoint = (
        f"{base}/wday/cxs/"
        f"{POSTMAN_TENANT}/{POSTMAN_BOARD}/jobs"
    )

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Origin": base,
        "Referer": f"{base}/en-US/{POSTMAN_BOARD}",
    }

    page_paths = {}

    print("\n[RECOVERY] POSTMAN WORKDAY")
    print(f"[POSTMAN] endpoint={endpoint}")

    for offset in (0, 20):
        try:
            response = requests.post(
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
                f"[POSTMAN] offset={offset} "
                f"status={response.status_code} "
                f"type={response.headers.get('Content-Type')!r}"
            )

            response.raise_for_status()

            data = response.json()

            if not isinstance(data, dict):
                raise ValueError("Expected JSON object")

            postings = data.get("jobPostings")

            if not isinstance(postings, list):
                raise ValueError("Missing jobPostings list")

            paths = {
                str(job["externalPath"])
                for job in postings
                if isinstance(job, dict)
                and job.get("externalPath")
            }

            page_paths[offset] = paths

            print(
                f"[POSTMAN] offset={offset} "
                f"total={data.get('total')!r} "
                f"count={len(postings)} "
                f"unique_paths={len(paths)}"
            )

            for job in postings[:8]:
                title = str(job.get("title", ""))
                location = str(job.get("locationsText", ""))

                print(
                    "[POSTMAN] SAMPLE "
                    f"title={title!r} "
                    f"location={location!r} "
                    f"path={job.get('externalPath')!r}"
                )

                if (
                    RECOVERY_ROLE_PATTERN.search(title)
                    and RECOVERY_INDIA_PATTERN.search(location)
                ):
                    print("[POSTMAN] RELEVANT_INDIA_ROLE")

        except (
            requests.RequestException,
            ValueError,
        ) as exc:
            print(
                f"[POSTMAN] offset={offset} "
                f"ERROR={type(exc).__name__}: {exc}"
            )

    if 0 in page_paths and 20 in page_paths:
        print(
            "[POSTMAN] page_overlap="
            f"{len(page_paths[0] & page_paths[20])}"
        )
        print(
            "[POSTMAN] distinct_pages="
            f"{page_paths[0] != page_paths[20]}"
        )

    print("[POSTMAN] Probe completed; inventory not yet certified")


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

    probe_postman_workday()

    session = requests.Session()
    session.headers.update(HEADERS)

    for name, url in RECOVERY_TARGETS.items():
        probe_recovery_html(name, url, session)
        time.sleep(DELAY_SECONDS)

    print("\n[RECOVERY] COMPLETE")
    print("[RECOVERY] No registry or state changes")
    print("[RECOVERY] No Telegram notifications")
    print("[RECOVERY] No automatic ATS replacement")


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

    args = parser.parse_args()

    if args.stale_recovery:
        run_stale_recovery()
    else:
        main()
