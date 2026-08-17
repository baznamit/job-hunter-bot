from models import PageSnapshot
from models.company import ProviderType
from research.detectors.workday import WorkdayDetector


def _snapshot(
    html: str = "",
    final_url: str = "https://example.com/careers",
) -> PageSnapshot:
    return PageSnapshot(
        original_url="https://example.com/careers",
        final_url=final_url,
        status_code=200,
        html=html,
        headers={},
    )


def test_detects_workday_from_final_url():
    snapshot = _snapshot(
        final_url=(
            "https://visa.wd5.myworkdayjobs.com/"
            "en-US/Visa"
        )
    )

    result = WorkdayDetector().detect(snapshot)

    assert result is not None
    assert result.provider == ProviderType.WORKDAY
    assert result.identifier == "Visa"

    assert result.config == {
        "tenant": "visa",
        "cluster": "wd5",
        "board": "Visa",
    }


def test_detects_workday_from_html():
    snapshot = _snapshot(
        html="""
        <html>
            <body>
                <a href="
                    https://microsoft.wd5.myworkdayjobs.com/en-US/Careers
                ">
                    View jobs
                </a>
            </body>
        </html>
        """
    )

    result = WorkdayDetector().detect(snapshot)

    assert result is not None
    assert result.provider == ProviderType.WORKDAY

    assert result.config == {
        "tenant": "microsoft",
        "cluster": "wd5",
        "board": "Careers",
    }


def test_detects_workday_without_locale():
    snapshot = _snapshot(
        final_url=(
            "https://example.wd3.myworkdayjobs.com/"
            "ExampleCareers"
        )
    )

    result = WorkdayDetector().detect(snapshot)

    assert result is not None

    assert result.config == {
        "tenant": "example",
        "cluster": "wd3",
        "board": "ExampleCareers",
    }


def test_does_not_detect_normal_page():
    snapshot = _snapshot(
        html="<html><body>Careers</body></html>"
    )

    result = WorkdayDetector().detect(snapshot)

    assert result is None


def test_rejects_workday_api_path_as_board():
    snapshot = _snapshot(
        html=(
            "https://visa.wd5.myworkdayjobs.com/"
            "wday/cxs/visa/Visa/jobs"
        )
    )

    result = WorkdayDetector().detect(snapshot)

    assert result is None