import json
import re
import time
from typing import Any, Iterable
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


USER_AGENT = "Mozilla/5.0"


def _clean(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return re.sub(r"\s+", " ", text)


def _get(url: str, timeout: int = 20, **kwargs: Any) -> requests.Response:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    headers.update(kwargs.pop("headers", {}))
    response = requests.get(
        url,
        timeout=timeout,
        headers=headers,
        **kwargs,
    )
    response.raise_for_status()
    return response


def _summary(text: str, limit: int = 180) -> str:
    cleaned = _clean(text)
    if not cleaned:
        return ""
    return cleaned[:limit]


def _blocked(text: str) -> bool:
    lowered = (text or "").lower()
    blocked_terms = (
        "captcha",
        "access denied",
        "blocked",
        "too many requests",
        "verify you are human",
    )
    return any(term in lowered for term in blocked_terms)


def _extract_links(html: str, base_url: str = "") -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links: list[str] = []
    for tag in soup.find_all("a", href=True):
        href = tag.get("href")
        if not href:
            continue
        url = href.strip()
        if not url:
            continue
        if base_url:
            url = urljoin(base_url, url)
        links.append(url)
    return links


def _extract_scripts(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    scripts: list[str] = []
    for tag in soup.find_all("script"):
        script = tag.get_text("", strip=True)
        if script:
            scripts.append(script)
    return scripts


def _contexts(text: str, terms: Iterable[str]) -> list[str]:
    haystack = (text or "").lower()
    matches: list[str] = []
    for term in terms:
        lowered = str(term).lower()
        if lowered in haystack:
            matches.append(str(term))
    return matches


def _job_links(page_url: str, html: str) -> list[str]:
    urls: list[str] = []
    for link in _extract_links(html, page_url):
        lower = link.lower()
        if (
            "careers" in lower
            or "job" in lower
            or "apply" in lower
            or "opportunity" in lower
        ) and not lower.startswith("mailto:"):
            urls.append(link)
    seen: set[str] = set()
    unique: list[str] = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            unique.append(url)
    return unique


def _inspect_rmk_page(url: str) -> dict[str, Any]:
    try:
        response = _get(url)
    except Exception as exc:  # pragma: no cover - probe script
        return {
            "url": url,
            "ok": False,
            "error": str(exc),
        }

    html = response.text or ""
    summary = _summary(html)
    return {
        "url": url,
        "ok": True,
        "status": response.status_code,
        "summary": summary,
        "job_links": _job_links(url, html),
    }


def _probe_rmk_candidate(url: str) -> dict[str, Any]:
    result = _inspect_rmk_page(url)
    if not result.get("ok"):
        return result
    job_links = result.get("job_links", [])
    result["candidate"] = bool(job_links)
    return result


def _probe_rss(url: str) -> dict[str, Any]:
    try:
        response = _get(url)
    except Exception as exc:
        return {
            "url": url,
            "ok": False,
            "error": str(exc),
        }

    text = response.text or ""
    return {
        "url": url,
        "ok": True,
        "status": response.status_code,
        "summary": _summary(text),
        "links": _job_links(url, text),
    }


def _probe_rmk(url: str) -> dict[str, Any]:
    result = _probe_rmk_candidate(url)
    if result.get("candidate"):
        return result

    rss_url = url.rstrip("/") + "/rss"
    rss_result = _probe_rss(rss_url)
    result["rss"] = rss_result
    return result


def _inspect_embedded_json(html: str) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for match in re.finditer(r"(\{.*?\})", html, flags=re.DOTALL):
        candidate = match.group(1)
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            matches.append(payload)
    return matches


def probe_capgemini() -> None:
    print("[CAPGEMINI] probing careers page")
    urls = [
        "https://www.capgemini.com/careers/",
        "https://www.capgemini.com/careers/find-your-role/",
    ]
    for url in urls:
        try:
            response = _get(url)
        except Exception as exc:
            print(f"  {url} -> ERROR: {exc}")
            continue
        html = response.text or ""
        print(f"  {url} -> status={response.status_code} summary={_summary(html)}")
        print(f"    job_links={len(_job_links(url, html))}")


def probe_ltm() -> None:
    print("[LTM] probing careers page")
    urls = [
        "https://www.ltimindtree.com/careers",
        "https://www.ltimindtree.com/careers/",
    ]
    for url in urls:
        try:
            response = _get(url)
        except Exception as exc:
            print(f"  {url} -> ERROR: {exc}")
            continue
        html = response.text or ""
        text = _summary(html)
        print(f"  {url} -> status={response.status_code} summary={text}")
        print(f"    job_links={len(_job_links(url, html))}")


def probe_clevertap() -> None:
    print("[CLEVERTAP] probing careers page")
    urls = [
        "https://clevertap.com/careers/",
        "https://clevertap.com/careers/jobs/",
    ]
    for url in urls:
        try:
            response = _get(url)
        except Exception as exc:
            print(f"  {url} -> ERROR: {exc}")
            continue
        html = response.text or ""
        print(f"  {url} -> status={response.status_code} summary={_summary(html)}")
        embedded = _inspect_embedded_json(html)
        print(f"    embedded_json={len(embedded)}")
        print(f"    job_links={len(_job_links(url, html))}")


def _run(label: str, probe_func) -> None:
    print()
    print(f"[BATCH-PROBE] {label}")
    try:
        probe_func()
    except Exception as exc:  # pragma: no cover - probe script
        print(f"  [ERROR] {label}: {exc}")


def main() -> None:
    print(
        "[BATCH-PROBE] "
        "Starting unresolved company batch"
    )

    _run(
        "Capgemini",
        probe_capgemini,
    )

    _run(
        "LTIMindtree / LTM",
        probe_ltm,
    )

    _run(
        "CleverTap",
        probe_clevertap,
    )

    print()
    print(
        "[BATCH-PROBE] Finished"
    )


if __name__ == "__main__":
    main()