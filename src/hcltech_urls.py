from __future__ import annotations

import re
from urllib.parse import quote, unquote, urlsplit


BASE_URL = "https://careers.hcltech.com"
LOCALE = "en_US"

_JOB_ID_PATTERN = re.compile(r"[0-9]+")
_JOB_PATH_PATTERN = re.compile(
    r"/job/(?P<slug>[^/]+)/(?P<job_id>[0-9]+)"
    r"(?:-en_US)?/?"
)


def canonical_hcltech_job_url(job_id: object, slug: object) -> str:
    identifier = str(job_id or "").strip()
    if not _JOB_ID_PATTERN.fullmatch(identifier):
        raise ValueError("Malformed HCLTech job ID")

    raw_slug = str(slug or "").strip().strip("/")
    if not raw_slug:
        raise ValueError("Missing HCLTech URL slug")

    normalized_slug = quote(
        unquote(raw_slug),
        safe="-._~",
    )
    return (
        f"{BASE_URL}/job/{normalized_slug}/"
        f"{identifier}-{LOCALE}"
    )


def hcltech_seen_key(value: object) -> str:
    raw_url = str(value)
    parsed = urlsplit(raw_url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "careers.hcltech.com"
        or parsed.query
        or parsed.fragment
    ):
        return raw_url

    match = _JOB_PATH_PATTERN.fullmatch(parsed.path)
    if match is None:
        return raw_url

    try:
        return canonical_hcltech_job_url(
            match.group("job_id"),
            unquote(match.group("slug")),
        )
    except ValueError:
        return raw_url
