import json
from types import SimpleNamespace

import pytest

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
