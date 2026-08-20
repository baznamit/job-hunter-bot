import re
import sys

import requests


_URL = (
    "https://bwelcome.hr.bnpparibas/"
    "en_US/externalcareers/SearchJobs"
)

_TIMEOUT = 30


def probe_bnp() -> None:
    response = requests.get(
        _URL,
        params={
            "search": "Java",
            "jobOffset": 0,
        },
        headers={
            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/127.0.0.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,"
                "application/xml;q=0.9,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        },
        timeout=_TIMEOUT,
        allow_redirects=True,
    )

    print(
        f"[BNP-PROBE] status={response.status_code}",
        file=sys.stderr,
    )

    print(
        f"[BNP-PROBE] final_url={response.url}",
        file=sys.stderr,
    )

    print(
        "[BNP-PROBE] content_type="
        f"{response.headers.get('Content-Type')}",
        file=sys.stderr,
    )

    print(
        f"[BNP-PROBE] server="
        f"{response.headers.get('Server')}",
        file=sys.stderr,
    )

    print(
        f"[BNP-PROBE] body_length="
        f"{len(response.content)}",
        file=sys.stderr,
    )

    body = response.text

    print(
        "[BNP-PROBE] body_preview="
        + repr(body[:1000]),
        file=sys.stderr,
    )

    if response.status_code != 200:
        return

    job_ids = set(
        re.findall(
            r'jobId[=/?:&]+(\d+)',
            body,
            flags=re.IGNORECASE,
        )
    )

    detail_links = re.findall(
        r'href=["\']([^"\']*'
        r'(?:JobDetail|JobDetails)'
        r'[^"\']*)["\']',
        body,
        flags=re.IGNORECASE,
    )

    print(
        f"[BNP-PROBE] job_ids_found="
        f"{len(job_ids)}",
        file=sys.stderr,
    )

    print(
        f"[BNP-PROBE] detail_links_found="
        f"{len(detail_links)}",
        file=sys.stderr,
    )

    for job_id in list(job_ids)[:5]:
        print(
            f"[BNP-PROBE] JOB_ID={job_id}",
            file=sys.stderr,
        )

    for link in detail_links[:5]:
        print(
            f"[BNP-PROBE] DETAIL_LINK={link}",
            file=sys.stderr,
        )


if __name__ == "__main__":
    probe_bnp()