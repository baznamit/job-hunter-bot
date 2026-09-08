import re

import requests

BASE_URL = "https://apply.careers.microsoft.com"

HEADERS = {
    "Accept": "text/html,application/json",
    "User-Agent": (
        "Mozilla/5.0 "
        "(compatible; JobHunterBot/1.0)"
    ),
}

TIMEOUT = 20

MARKERS = (
    "search_positions",
    "searchPositions",
    "position/search",
    "positions/search",
    "/api/positions",
    "/api/search",
    "pcsx",
    "basePositionFq",
    "position_fq",
    "positionFq",
    "fetch(",
    "axios",
)

def fetch(path: str) -> requests.Response:
    url = f"{BASE_URL}{path}"

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=TIMEOUT,
    )

    print(
        f"[MS-EIGHTFOLD] GET {path}: "
        f"status={response.status_code} "
        f"final={response.url} "
        f"length={len(response.content)}"
    )

    return response

def show_matches(
    text: str,
    marker: str,
) -> None:
    lower = text.lower()
    needle = marker.lower()

    start = 0
    count = 0

    while count < 10:
        index = lower.find(
            needle,
            start,
        )

        if index < 0:
            break

        left = max(
            0,
            index - 300,
        )

        right = min(
            len(text),
            index + 700,
        )

        context = " ".join(
            text[left:right].split()
        )

        print(
            f"[MS-EIGHTFOLD] "
            f"marker={marker!r} "
            f"context={context!r}"
        )

        start = index + len(marker)
        count += 1

def main() -> None:
    response = fetch("/careers")

    response.raise_for_status()

    html = response.text

    for marker in MARKERS:
        show_matches(
            html,
            marker,
        )

    scripts = re.findall(
        r'<script[^>]+src=["\']([^"\']+)["\']',
        html,
        flags=re.IGNORECASE,
    )

    print(
        f"[MS-EIGHTFOLD] scripts={len(scripts)}"
    )

    for script in scripts:
        if script.startswith("//"):
            script = "https:" + script

        elif script.startswith("/"):
            script = BASE_URL + script

        if not script.startswith("http"):
            continue

        if not (
            "apply.careers.microsoft.com/gen/js/ef-" in script
            or "pcsx" in script.lower()
        ):
            continue

        try:
            script_response = requests.get(
                script,
                headers=HEADERS,
                timeout=TIMEOUT,
            )
        except requests.RequestException:
            continue

        text = script_response.text

        interesting = any(
            marker.lower() in text.lower()
            for marker in MARKERS
        )

        if not interesting:
            continue

        print(
            f"[MS-EIGHTFOLD] SCRIPT "
            f"url={script_response.url} "
            f"status={script_response.status_code} "
            f"length={len(text)}"
        )

        for marker in MARKERS:
            show_matches(
                text,
                marker,
            )

if __name__ == "__main__":
    main()
