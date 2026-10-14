
from __future__ import annotations

import json
import requests

BASE = (
    "https://intapgateway.infosysapps.com/"
    "careers/search/intapjbsrch/"
)

CONFIG_URL = (
    "https://career.infosys.com/"
    "assets/environments/environment.json"
)

TIMEOUT = 30

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Origin": "https://career.infosys.com",
    "Referer": "https://career.infosys.com/jobs",
}


def inspect_json(label, response):
    print(
        f"[{label}] "
        f"status={response.status_code} "
        f"content_type={response.headers.get('Content-Type')} "
        f"bytes={len(response.content)}"
    )

    try:
        payload = response.json()
    except ValueError:
        print(
            f"[{label}] NON_JSON "
            f"preview={response.text[:300]!r}"
        )
        return

    if isinstance(payload, dict):
        print(
            f"[{label}] "
            f"keys={list(payload.keys())}"
        )

        for key, value in payload.items():
            if isinstance(value, list):
                print(
                    f"[{label}] "
                    f"list={key} count={len(value)}"
                )

                if value:
                    print(
                        f"[{label}] "
                        f"sample={json.dumps(value[0], default=str)[:2000]}"
                    )

            elif isinstance(value, dict):
                print(
                    f"[{label}] "
                    f"object={key} "
                    f"keys={list(value.keys())}"
                )

    elif isinstance(payload, list):
        print(
            f"[{label}] "
            f"jobs={len(payload)}"
        )

        for item in payload[:3]:
            print(
                f"[{label}] "
                f"sample={json.dumps(item, default=str)[:2000]}"
            )


def main():
    with requests.Session() as session:
        session.headers.update(HEADERS)

        print("\n========== CONFIG ==========")

        response = session.get(
            CONFIG_URL,
            timeout=TIMEOUT,
        )
        response.raise_for_status()

        config = response.json()

        base = str(
            config.get("JobsUnAuthUrl") or ""
        ).strip()

        if not base:
            raise RuntimeError(
                "JobsUnAuthUrl missing from environment.json"
            )

        print(
            "[INF-CONFIG] JobsUnAuthUrl host="
            f"{requests.utils.urlparse(base).netloc}"
        )

        endpoint = base.rstrip("/") + "/getCareerSearchJobs"

        print("\n========== PUBLIC JOBS ==========")

        for source_id in ("1,21", "1", "21"):
            try:
                response = session.get(
                    endpoint,
                    params={
                        "sourceId": source_id,
                        "searchText": "ALL",
                    },
                    timeout=TIMEOUT,
                    headers={
                        "Accept": "application/json",
                        "Origin": "https://career.infosys.com",
                        "Referer": "https://career.infosys.com/jobs",
                    },
                )

                print(
                    f"[INF-JOBS] "
                    f"sourceId={source_id} "
                    f"status={response.status_code} "
                    f"final={response.url} "
                    f"content_type={response.headers.get('Content-Type')}"
                )

                inspect_json(
                    f"INF-JOBS sourceId={source_id}",
                    response,
                )

            except requests.RequestException as exc:
                print(
                    f"[INF-JOBS] "
                    f"sourceId={source_id} "
                    f"ERROR {type(exc).__name__}: {exc}"
                )


if __name__ == "__main__":
    main()
