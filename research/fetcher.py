import requests

from models import PageSnapshot


DEFAULT_TIMEOUT = 15


def fetch_page(url: str) -> PageSnapshot:
    """
    Fetch a web page and return a PageSnapshot.
    """

    response = requests.get(
        url,
        timeout=DEFAULT_TIMEOUT,
        allow_redirects=True,
        headers={
            "User-Agent": (
                "JobHunterBot/1.0 "
                "(https://github.com/baznamit/job-hunter-bot)"
            )
        },
    )

    response.raise_for_status()

    return PageSnapshot(
        original_url=url,
        final_url=str(response.url),
        status_code=response.status_code,
        html=response.text,
        headers=dict(response.headers),
    )