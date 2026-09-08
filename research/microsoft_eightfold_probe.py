import json

import requests

_BASE_URL = (
    "https://apply.careers.microsoft.com"
)

_ENDPOINT = (
    f"{_BASE_URL}/api/pcsx/search"
)

_TIMEOUT = 30

_HEADERS = {
    "Accept": "application/json",
    "User-Agent": (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/127.0.0.0 Safari/537.36"
    ),
}

def _probe(
    label: str,
    params: dict,
) -> None:
    response = requests.get(
        _ENDPOINT,
        params=params,
        headers=_HEADERS,
        timeout=_TIMEOUT,
        allow_redirects=False,
    )

    print(
        f"[MS-API] {label}: "
        f"status={response.status_code} "
        f"url={response.url} "
        f"content_type="
        f"{response.headers.get('Content-Type')} "
        f"location="
        f"{response.headers.get('Location')} "
        f"length={len(response.content)}"
    )

    print(
        f"[MS-API] {label}: "
        f"body={response.text[:3000]!r}"
    )

    if response.status_code != 200:
        return

    try:
        payload = response.json()
    except requests.exceptions.JSONDecodeError:
        return

    print(
        f"[MS-API] {label}: "
        f"top_type="
        f"{type(payload).__name__}"
    )

    if not isinstance(
        payload,
        dict,
    ):
        return

    print(
        f"[MS-API] {label}: "
        f"top_keys="
        f"{list(payload.keys())}"
    )

    data = payload.get(
        "data"
    )

    if not isinstance(
        data,
        dict,
    ):
        return

    print(
        f"[MS-API] {label}: "
        f"data_keys="
        f"{list(data.keys())}"
    )

    print(
        f"[MS-API] {label}: "
        f"count={data.get('count')}"
    )

    positions = (
        data.get("positions")
        or []
    )

    print(
        f"[MS-API] {label}: "
        f"positions={len(positions)}"
    )

    if positions:
        first = positions[0]

        print(
            f"[MS-API] {label}: "
            f"first_keys="
            f"{list(first.keys())}"
        )

        compact = {
            key: value
            for key, value
            in first.items()
            if key not in (
                "description",
                "job_description",
            )
        }

        print(
            f"[MS-API] {label}: "
            f"first={json.dumps(compact)[:5000]}"
        )

def main() -> None:
    common = {
        "domain": "microsoft.com",
        "location": "",
        "start": 0,
    }

    _probe(
        "all",
        {
            **common,
            "query": "",
        },
    )

    _probe(
        "software-engineer",
        {
            **common,
            "query":
                "Software Engineer",
        },
    )

    _probe(
        "java",
        {
            **common,
            "query": "Java",
        },
    )

if __name__ == "__main__":
    main()
