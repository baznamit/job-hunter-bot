from __future__ import annotations

import argparse
import re
from html.parser import HTMLParser
from urllib.parse import urljoin

import requests

TIMEOUT = 30

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "text/html,application/json,*/*",
}

BNP_URL = (
    "https://group.bnpparibas/"
    "en/careers/all-job-offers/india"
)

INFOSYS_URL = "https://career.infosys.com"

class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)

        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])

        if tag == "script" and attrs.get("src"):
            self.scripts.append(attrs["src"])

def fetch(session, label, url):
    try:
        response = session.get(
            url,
            timeout=TIMEOUT,
            allow_redirects=True,
        )

        print(
            f"[{label}] "
            f"status={response.status_code} "
            f"url={response.url} "
            f"bytes={len(response.content)} "
            f"type={response.headers.get('Content-Type')}"
        )

        if response.history:
            print(
                f"[{label}] redirects="
                f"{[(r.status_code, r.url) for r in response.history]}"
            )

        if response.status_code != 200:
            print(
                f"[{label}] preview="
                f"{response.text[:300]!r}"
            )

        return response

    except requests.RequestException as exc:
        print(
            f"[{label}] ERROR "
            f"{type(exc).__name__}: {exc}"
        )
        return None

def inspect(label, response, company):
    if response is None or response.status_code != 200:
        return set()

    parser = LinkParser()
    parser.feed(response.text)

    links = [
        urljoin(response.url, href)
        for href in parser.links
    ]

    if company == "bnp":
        jobs = {
            url for url in links
            if "/careers/job-offer/" in url
        }
    else:
        jobs = {
            url for url in links
            if "jobdesc" in url.lower()
            or "jobreferencecode" in url.lower()
        }

    print(
        f"[{label}] "
        f"links={len(links)} "
        f"job_links={len(jobs)} "
        f"scripts={len(parser.scripts)}"
    )

    for url in sorted(jobs)[:15]:
        print(f"[{label}] JOB {url}")

    for url in links:
        if any(
            term in url.lower()
            for term in ("page=", "next", "joblist")
        ):
            print(f"[{label}] NAV {url[:220]}")

    for script in parser.scripts[:15]:
        print(
            f"[{label}] SCRIPT "
            f"{urljoin(response.url, script)}"
        )

    for marker in (
        "__NEXT_DATA__",
        "__INITIAL_STATE__",
        "graphql",
        "application/ld+json",
        "jobReferenceCode",
    ):
        print(
            f"[{label}] marker={marker} "
            f"present={marker.lower() in response.text.lower()}"
        )

    return jobs

def probe_bnp(session):
    print("\n========== BNP PARIBAS ==========")

    pages = {}

    candidates = {
        "BNP-BASE": BNP_URL,
        "BNP-PAGE1": BNP_URL + "?page=1",
        "BNP-PAGE2": BNP_URL + "?page=2",
        "BNP-PERM": (
            "https://group.bnpparibas/"
            "en/careers/all-job-offers/"
            "permanent/india?page=1"
        ),
    }

    for label, url in candidates.items():
        response = fetch(session, label, url)
        pages[label] = inspect(label, response, "bnp")

    baseline = pages["BNP-BASE"]

    for label, jobs in pages.items():
        print(
            f"[BNP-COMPARE] {label} "
            f"count={len(jobs)} "
            f"overlap={len(baseline & jobs)} "
            f"different={jobs != baseline}"
        )

    detail_url = (
        "https://group.bnpparibas/"
        "en/careers/job-offer/"
        "java-backend-developer"
    )

    response = fetch(
        session,
        "BNP-DETAIL",
        detail_url,
    )

    if response is not None and response.status_code == 200:
        parser = LinkParser()
        parser.feed(response.text)

        for href in parser.links:
            if any(
                term in href.lower()
                for term in ("apply", "bwelcome", "postuler")
            ):
                print(
                    "[BNP-APPLY] "
                    + urljoin(response.url, href)
                )

def probe_infosys(session):
    print("\n========== INFOSYS ==========")

    candidates = {
        "INF-JOBS": (
            INFOSYS_URL
            + "/jobs?companyhiringtype=IL&countrycode=IN"
        ),
        "INF-JOBLIST": INFOSYS_URL + "/joblist",
        "INF-DETAIL": (
            INFOSYS_URL
            + "/jobdesc?jobReferenceCode="
            + "INFSYS-EXTERNAL-254157"
        ),
    }

    for label, url in candidates.items():
        response = fetch(session, label, url)
        inspect(label, response, "infosys")

        if response is None or response.status_code != 200:
            continue

        text = response.text

        markers = (
            "jobReferenceCode",
            "companyhiringtype",
            "countrycode",
            "graphql",
            "/api/",
            "fetch(",
            "axios",
            "pagination",
            "totalJobs",
        )

        for marker in markers:
            matches = list(
                re.finditer(
                    re.escape(marker),
                    text,
                    re.IGNORECASE,
                )
            )

            print(
                f"[{label}] "
                f"marker={marker!r} "
                f"occurrences={len(matches)}"
            )

            for match in matches[:2]:
                snippet = text[
                    max(0, match.start() - 100):
                    match.end() + 150
                ]

                snippet = re.sub(
                    r"\s+",
                    " ",
                    snippet,
                )

                print(
                    f"[{label}] CONTEXT "
                    f"{snippet[:250]!r}"
                )

def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--company",
        choices=("all", "bnp", "infosys"),
        default="all",
    )

    args = parser.parse_args()

    with requests.Session() as session:
        session.headers.update(HEADERS)

        if args.company in ("all", "bnp"):
            probe_bnp(session)

        if args.company in ("all", "infosys"):
            probe_infosys(session)

if __name__ == "__main__":
    main()