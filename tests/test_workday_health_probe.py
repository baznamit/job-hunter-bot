import builtins
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import requests

from models.company import ProviderType
from research import loader
from research import company_probe as probe


class FakeResponse:
    def __init__(self, status=200, body=b"{}", url="https://final.example/", headers=None, history=None):
        self.status_code = status
        self.content = body
        self.url = url
        self.headers = headers or {"Content-Type": "application/json"}
        self.history = history or []
        self.encoding = "utf-8"


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def company(company_id="acme", boards=None, board="careers"):
    return SimpleNamespace(
        id=company_id,
        name=company_id.title(),
        enabled=True,
        provider=SimpleNamespace(
            type=ProviderType.WORKDAY,
            config=SimpleNamespace(
                tenant=company_id,
                cluster="wd1",
                board=board,
                boards=boards or [],
            ),
        ),
    )


def patch_registry(monkeypatch, companies):
    monkeypatch.setattr(loader, "load_registry", lambda: SimpleNamespace(companies=companies))


def listing(total=21, postings=None):
    return FakeResponse(
        body=json.dumps({"jobPostings": postings or [{"externalPath": "/job/one", "locationsText": "Mumbai, India"}], "total": total}).encode(),
    )


def test_valid_json_and_distinct_second_page(monkeypatch, capsys):
    c = company()
    patch_registry(monkeypatch, [c])
    session = FakeSession([
        listing(postings=[{"externalPath": "/job/one", "locationsText": "Mumbai, India"}]),
        listing(postings=[{"externalPath": "/job/two", "locationsText": "Pune, India"}]),
    ])

    probe.run_workday_health(session=session, budget_seconds=10)

    assert [call[0] for call in session.calls] == ["POST", "POST"]
    assert session.calls[1][2]["json"]["offset"] == 20
    output = capsys.readouterr().out
    assert "observed_listing_count=2" in output
    assert "distinct_externalPath=2" in output
    assert "exhaustive_inventory=NO" in output


@pytest.mark.parametrize("response, expected", [
    (FakeResponse(headers={"Content-Type": "text/html"}, body=b"<html>blocked</html>"), "not-json"),
    (FakeResponse(body=b""), "not-json"),
    (FakeResponse(body=b"{broken"), "not-json"),
])
def test_non_json_responses_are_summarized(monkeypatch, capsys, response, expected):
    patch_registry(monkeypatch, [company()])
    probe.run_workday_health(session=FakeSession([response]), budget_seconds=10)
    output = capsys.readouterr().out
    assert f"json={expected}" in output
    assert "preview=" in output


def test_redirect_evidence_and_access_stops_host(monkeypatch, capsys):
    patch_registry(monkeypatch, [company("first"), company("second")])
    redirect = FakeResponse(
        status=200,
        url="https://final.example/",
        history=[FakeResponse(status=302, url="https://redirect.example/", headers={"Location": "https://final.example/"})],
    )
    blocked = FakeResponse(status=403, body=b"forbidden", url="https://first.wd1.myworkdayjobs.com/blocked", headers={"Content-Type": "text/html"})
    session = FakeSession([redirect, blocked])

    probe.run_workday_health(session=session, budget_seconds=10)

    assert len(session.calls) == 2
    assert "redirects=302->https://final.example/" in capsys.readouterr().out


def test_timeout_isolated_and_overall_budget_exhaustion(monkeypatch):
    patch_registry(monkeypatch, [company("first"), company("second")])
    session = FakeSession([TimeoutError("slow"), listing(total=1)])
    probe.run_workday_health(session=session, budget_seconds=10)
    assert len(session.calls) == 2

    session = FakeSession([listing()])
    probe.run_workday_health(session=session, budget_seconds=0)
    assert session.calls == []


def test_multiple_boards_salesforce_detail_failure_and_no_candidates(monkeypatch, capsys):
    multi = company("multi", boards=["one", "two"], board=None)
    salesforce = company("salesforce", board="External_Career_Site")
    patch_registry(monkeypatch, [multi, salesforce])
    session = FakeSession([
        listing(total=1), listing(total=1),
        listing(total=1, postings=[{"externalPath": "/job/one", "locationsText": "2 Locations"}]),
        TimeoutError("detail unavailable"),
    ])

    probe.run_workday_health(session=session, budget_seconds=10)

    assert [call[0] for call in session.calls] == ["POST", "POST", "POST", "GET"]
    output = capsys.readouterr().out
    assert "requested_url=https://salesforce.wd1.myworkdayjobs.com/wday/cxs/salesforce/External_Career_Site/job/one" in output

    patch_registry(monkeypatch, [salesforce])
    session = FakeSession([listing(total=1, postings=[{"externalPath": "/job/one", "locationsText": "Mumbai, India"}])])
    probe.run_workday_health(session=session, budget_seconds=10)
    assert "salesforce_detail=NOT_SAMPLED" in capsys.readouterr().out


def test_no_persistent_writes_or_telegram_calls(monkeypatch):
    patch_registry(monkeypatch, [company()])
    session = FakeSession([listing(total=1)])
    probe.run_workday_health(session=session, budget_seconds=10)
    assert not hasattr(session, "telegram")


def test_health_labels_maintenance_and_does_not_rediscover(monkeypatch, capsys):
    patch_registry(monkeypatch, [company("maintenance")])
    redirect = FakeResponse(
        status=303,
        url="https://maintenance.wd1.myworkdayjobs.com/wday/cxs/maintenance/careers/jobs",
        headers={"Location": "https://community.workday.com/maintenance-page"},
    )
    final = FakeResponse(
        status=200,
        body=b"<html>maintenance</html>",
        url="https://community.workday.com/maintenance-page",
        headers={"Content-Type": "text/html"},
        history=[redirect],
    )
    session = FakeSession([final])

    with patch("src.providers.workday.WorkdayAdapter.fetch_jobs", side_effect=AssertionError("rediscovery")):
        probe.run_workday_health(session=session, budget_seconds=10)

    output = capsys.readouterr().out
    assert "classification=TEMPORARY_MAINTENANCE" in output
    assert "summary_status=TEMPORARY_MAINTENANCE" in output


def test_health_labels_later_page_failure_incomplete(monkeypatch, capsys):
    patch_registry(monkeypatch, [company("later")])
    session = FakeSession([
        listing(total=21),
        FakeResponse(status=200, body=b"{bad", headers={"Content-Type": "application/json"}),
    ])

    probe.run_workday_health(session=session, budget_seconds=10)

    output = capsys.readouterr().out
    assert "pagination_evidence=INCOMPLETE" in output


class SampleResponse:
    def __init__(self, status=200, headers=None):
        self.status_code = status
        self.headers = requests.structures.CaseInsensitiveDict(headers or {})
        self.closed = False

    @property
    def content(self):
        raise AssertionError("diagnostic must not read the response body")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True


class SampleSession:
    def __init__(self, result):
        self.result = result
        self.calls = []
        self.trust_env = True
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_rate_limit_sample_uses_only_verified_allowlist_and_one_listing_each(monkeypatch, capsys):
    sessions = [SampleSession(SampleResponse()) for _ in range(4)]
    factory = iter(sessions)
    sleeps = []
    monkeypatch.setattr(probe.requests, "Session", lambda: next(factory))
    monkeypatch.setattr(probe.time, "sleep", sleeps.append)
    monkeypatch.setattr(Path, "write_text", lambda *args, **kwargs: pytest.fail("state write"))
    monkeypatch.setattr(Path, "write_bytes", lambda *args, **kwargs: pytest.fail("state write"))
    original_open = Path.open
    original_builtin_open = builtins.open

    def read_only_open(path, mode="r", *args, **kwargs):
        assert not any(flag in mode for flag in "wax+"), "state write"
        return original_open(path, mode, *args, **kwargs)

    def read_only_builtin_open(file, mode="r", *args, **kwargs):
        assert not any(flag in mode for flag in "wax+"), "state write"
        return original_builtin_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", read_only_open)
    monkeypatch.setattr(builtins, "open", read_only_builtin_open)
    with patch("src.recovery_store.RecoveryStore.record_failure") as record, \
         patch("src.recovery_store.RecoveryStore.clear") as clear, \
         patch("src.notifier.TelegramNotifier.send_message") as send:
        probe.run_workday_rate_limit_sample()
    record.assert_not_called()
    clear.assert_not_called()
    send.assert_not_called()

    urls = [session.calls[0][0] for session in sessions]
    assert urls == [
        "https://postman.wd108.myworkdayjobs.com/wday/cxs/postman/careers/jobs",
        "https://browserstack.wd3.myworkdayjobs.com/wday/cxs/browserstack/External/jobs",
        "https://bakerhughes.wd5.myworkdayjobs.com/wday/cxs/bakerhughes/BakerHughes/jobs",
        "https://duckcreek.wd1.myworkdayjobs.com/wday/cxs/duckcreek/duckcreekcareers/jobs",
    ]
    assert sleeps == [5, 5, 5]
    for session in sessions:
        assert session.closed and not session.trust_env
        assert len(session.calls) == 1
        assert session.result.closed
        kwargs = session.calls[0][1]
        assert kwargs["json"] == {
            "appliedFacets": {}, "limit": 20, "offset": 0, "searchText": "",
        }
        assert kwargs["allow_redirects"] is False
        assert kwargs["stream"] is True
        assert kwargs["timeout"] == (5, 10)
    output = capsys.readouterr().out
    assert output.count("status=200") == 4
    assert "start_utc=" in output and "elapsed_seconds=" in output


def test_rate_limit_sample_stops_entirely_on_429_and_filters_headers(monkeypatch, capsys):
    responses = [
        SampleResponse(),
        SampleResponse(429, {
            "Retry-After": "30",
            "X-RateLimit-Remaining": "0",
            "RateLimit-Reset": "leak-secret",
            "Set-Cookie": "cookie-secret",
            "Authorization": "authorization-secret",
        }),
    ]
    sessions = [SampleSession(response) for response in responses]
    factory = iter(sessions)
    sleeps = []
    monkeypatch.setattr(probe.requests, "Session", lambda: next(factory))
    monkeypatch.setattr(probe.time, "sleep", sleeps.append)

    probe.run_workday_rate_limit_sample()

    assert [len(session.calls) for session in sessions] == [1, 1]
    assert sleeps == [5]
    output = capsys.readouterr().out
    assert 'status=429' in output
    assert '"retry-after": "30"' in output
    assert '"x-ratelimit-remaining": "0"' in output
    assert '"ratelimit-reset": "<omitted>"' in output
    assert "secret" not in output
    assert "stopped=rate_limit" in output


def test_rate_limit_sample_supports_http_date_and_reports_timing(monkeypatch, capsys):
    session = SampleSession(SampleResponse(429, {
        "Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT",
    }))
    monkeypatch.setattr(probe.requests, "Session", lambda: session)
    ticks = iter([100.0, 101.25])
    monkeypatch.setattr(probe.time, "monotonic", lambda: next(ticks))

    probe.run_workday_rate_limit_sample()

    output = capsys.readouterr().out
    assert '"retry-after": "Wed, 21 Oct 2015 07:28:00 GMT"' in output
    assert "elapsed_seconds=1.250" in output
    assert "start_utc=" in output


def test_rate_limit_sample_transport_error_stops_without_retry_or_leaking(monkeypatch, capsys):
    session = SampleSession(requests.Timeout("secret"))
    monkeypatch.setattr(probe.requests, "Session", lambda: session)
    with pytest.raises(RuntimeError, match="Timeout") as raised:
        probe.run_workday_rate_limit_sample()
    assert len(session.calls) == 1
    assert "secret" not in str(raised.value)
    assert "secret" not in capsys.readouterr().out


def test_rate_limit_sample_rejects_changed_mapping_before_any_request(monkeypatch):
    registry = loader.load_registry()
    registry.companies[0].provider.config.cluster = "wd999"
    monkeypatch.setattr(loader, "load_registry", lambda: registry)
    with patch.object(probe.requests, "Session") as factory:
        with pytest.raises(ValueError, match="duckcreek"):
            probe.run_workday_rate_limit_sample()
    factory.assert_not_called()


def test_rate_limit_sample_real_session_disables_redirects_retries_and_environment(monkeypatch):
    sent = []

    def send(adapter, request, **kwargs):
        sent.append(request)
        assert adapter.max_retries.total == 0
        assert not kwargs["proxies"]
        response = requests.Response()
        response.status_code = 302 if len(sent) == 1 else 429
        response.url = request.url
        response.request = request
        response.headers = requests.structures.CaseInsensitiveDict(
            {"Location": "https://example.invalid/redirect", "Set-Cookie": "secret=1"}
        )
        response._content = b""
        response._content_consumed = True
        return response

    monkeypatch.setenv("HTTPS_PROXY", "http://example.invalid:1234")
    monkeypatch.setattr(
        requests.sessions, "get_netrc_auth",
        lambda *args, **kwargs: pytest.fail("environment credentials accessed"),
    )
    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", send)
    monkeypatch.setattr(probe.time, "sleep", lambda delay: None)

    probe.run_workday_rate_limit_sample()

    assert len(sent) == 2
    assert all(request.method == "POST" for request in sent)
    assert all("Cookie" not in request.headers and "Authorization" not in request.headers for request in sent)
    assert sent[0].url.startswith("https://postman.wd108.myworkdayjobs.com/")
    assert sent[1].url.startswith("https://browserstack.wd3.myworkdayjobs.com/")
