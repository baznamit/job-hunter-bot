import re
import sys

import requests


def probe_oracle_page(url: str) -> None:
    response = requests.get(
        url,
        timeout=30,
        allow_redirects=True,
        headers={
            "User-Agent": "JobHunterBot/1.0",
            "Accept": "text/html,application/xhtml+xml",
        },
    )

    response.raise_for_status()

    print(
        f"[ORACLE-PROBE] final_url={response.url}",
        file=sys.stderr,
    )

    print(
        f"[ORACLE-PROBE] status={response.status_code}",
        file=sys.stderr,
    )

    html = response.text

    patterns = (
        r'https?://[^"\'\s<>]+oraclecloud\.com[^"\'\s<>]*',
        r'https?://[^"\'\s<>]+/hcmRestApi/[^"\'\s<>]*',
        r'[^"\'\s<>]+recruitingCEJobRequisitions[^"\'\s<>]*',
        r'[^"\'\s<>]+hcmRestApi[^"\'\s<>]*',
    )

    matches: set[str] = set()

    for pattern in patterns:
        matches.update(
            re.findall(
                pattern,
                html,
                flags=re.IGNORECASE,
            )
        )

    if not matches:
        print(
            "[ORACLE-PROBE] no API/backend references "
            "found in page HTML",
            file=sys.stderr,
        )
        return

    print(
        f"[ORACLE-PROBE] found {len(matches)} "
        "candidate reference(s):",
        file=sys.stderr,
    )

    for match in sorted(matches):
        print(
            f"[ORACLE-PROBE] {match[:500]}",
            file=sys.stderr,
        )


if __name__ == "__main__":
    probe_oracle_page(
        "https://careers.americanexpress.com/"
        "en/sites/CX_1/jobs"
    )