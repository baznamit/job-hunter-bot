from models import PageSnapshot
from models.company import ProviderType
from research.detectors import detect_provider


def _snapshot(html: str, final_url: str = "https://example.com/careers") -> PageSnapshot:
    return PageSnapshot(
        original_url="https://example.com/careers",
        final_url=final_url,
        status_code=200,
        html=html,
        headers={},
    )


def test_detects_greenhouse_from_embed_script():
    html = (
        '<script src="https://boards.greenhouse.io/embed/job_board/js'
        '?for=postman"></script>'
    )
    result = detect_provider(_snapshot(html))

    assert result.provider is ProviderType.GREENHOUSE
    assert result.identifier == "postman"
    assert result.confidence > 0.5


def test_detects_greenhouse_from_final_url_redirect():
    result = detect_provider(
        _snapshot("<html></html>", final_url="https://boards.greenhouse.io/figma")
    )

    assert result.provider is ProviderType.GREENHOUSE
    assert result.identifier == "figma"


def test_detects_greenhouse_from_api_url():
    html = '<a href="https://boards-api.greenhouse.io/v1/boards/stripe/jobs">Jobs</a>'
    result = detect_provider(_snapshot(html))

    assert result.provider is ProviderType.GREENHOUSE
    assert result.identifier == "stripe"


def test_unknown_when_no_ats_signature():
    result = detect_provider(_snapshot("<html><body>Careers</body></html>"))

    assert result.provider is ProviderType.UNKNOWN
    assert result.identifier is None
    assert result.confidence == 0.0
