import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import requests

from models import Job
from src.main import (
    _build_message_batches,
    _send_notifications,
)
from src.notifier import MAX_MESSAGE_LEN, TelegramNotifier, message_length
from src.store import SeenStore


def _job(number, *, title="Engineer", location="Mumbai, India", url=None):
    return Job(
        id=str(number),
        title=title,
        company="Acme",
        location=location,
        url=url or f"https://example.com/jobs/{number}?source=bot",
    )


def _settings():
    return {
        "locations": {
            "notification_priority": [
                {"name": "Mumbai", "terms": ["Mumbai"]},
                {"name": "Bengaluru", "terms": ["Bengaluru"]},
            ]
        }
    }


def test_zero_jobs_produces_no_batches():
    assert _build_message_batches([], 25, _settings()) == []


def test_seen_filter_deduplicates_unseen_urls_without_mutating_history(tmp_path):
    store = SeenStore(tmp_path / "seen.json")
    seen = _job(1)
    store.mark_seen([seen])
    first = _job(2, title="Same title")
    duplicate = _job(2, title="Same title", url=str(first.url))
    distinct = _job(2, title="Same title", url="https://example.com/jobs/other")

    before = store.count
    result = store.filter_new([seen, first, duplicate, distinct])
    assert result == [first, distinct]
    assert store.count == before
    assert store.filter_new([seen, first, duplicate, distinct]) == [first, distinct]


def test_count_limit_plans_all_jobs_once_with_complete_urls():
    jobs = [_job(index) for index in range(26)]
    batches = _build_message_batches(jobs, 25, _settings())

    assert [len(batch.jobs) for batch in batches] == [25, 1]
    planned = [str(job.url) for batch in batches for job in batch.jobs]
    assert planned == [str(job.url) for job in jobs]
    assert len(set(planned)) == 26
    assert all(message_length(batch.message) <= MAX_MESSAGE_LEN for batch in batches)
    assert "more job(s) not shown" not in "".join(batch.message for batch in batches)


def test_length_limit_splits_before_count_limit_and_repeats_groups():
    jobs = [
        _job(index, title="A" * 900, location="Mumbai, India")
        for index in range(5)
    ]
    batches = _build_message_batches(jobs, 25, _settings())

    assert len(batches) > 1
    assert all(message_length(batch.message) <= MAX_MESSAGE_LEN for batch in batches)
    assert all("📌 Mumbai" in batch.message for batch in batches)
    assert [job.id for batch in batches for job in batch.jobs] == [
        job.id for job in jobs
    ]


def test_unicode_and_long_fields_are_safe_and_urls_are_complete():
    job = _job(
        1,
        title="🚀 " * 200,
        location="Mumbai, India",
        url="https://example.com/jobs/1?query=पूर्ण&emoji=🚀",
    )
    batches = _build_message_batches([job], 1, _settings())

    assert len(batches) == 1
    assert str(job.url) in batches[0].message
    assert message_length(batches[0].message) <= MAX_MESSAGE_LEN


def test_invalid_limit_and_irreducibly_large_record_fail_before_send():
    with pytest.raises(ValueError, match="positive integer"):
        _build_message_batches([_job(1)], 0, _settings())

    oversized_url = SimpleNamespace(
        company="Acme",
        title="Engineer",
        location="Mumbai, India",
        url="https://example.com/" + ("x" * 5000),
    )
    with pytest.raises(ValueError, match="cannot fit"):
        _build_message_batches(
            [oversized_url],
            1,
            _settings(),
        )


class _Notifier:
    def __init__(self, failures=None):
        self.messages = []
        self.failures = set(failures or [])

    def send_message(self, message):
        self.messages.append(message)
        if len(self.messages) in self.failures:
            raise RuntimeError("simulated delivery failure")


def test_partial_delivery_persists_only_successful_batches_and_retry_is_pending(tmp_path):
    store = SeenStore(tmp_path / "seen.json")
    jobs = [_job(index) for index in range(3)]
    notifier = _Notifier(failures={2})

    with pytest.raises(SystemExit) as raised:
        _send_notifications(store, notifier, jobs, 2, _settings())

    assert raised.value.code == 1
    fresh = SeenStore(tmp_path / "seen.json")
    assert [job.id for job in fresh.filter_new(jobs)] == ["2"]
    assert len(notifier.messages) == 2

    retry_notifier = _Notifier()
    _send_notifications(
        fresh,
        retry_notifier,
        fresh.filter_new(jobs),
        2,
        _settings(),
    )
    assert len(retry_notifier.messages) == 1
    assert SeenStore(tmp_path / "seen.json").filter_new(jobs) == []


def test_persistence_failure_stops_after_acknowledged_send(tmp_path):
    path = tmp_path / "seen.json"
    store = SeenStore(path)
    notifier = _Notifier()

    with patch.object(store, "mark_seen", side_effect=OSError("disk full")):
        with pytest.raises(SystemExit) as raised:
            _send_notifications(
                store,
                notifier,
                [_job(1), _job(2)],
                1,
                _settings(),
            )

    assert raised.value.code == 1
    assert len(notifier.messages) == 1
    assert not path.exists()


def test_atomic_persistence_keeps_previous_valid_file_on_replace_failure(tmp_path):
    path = tmp_path / "seen.json"
    store = SeenStore(path)
    store.mark_seen([_job(1)])
    original = path.read_text()

    with patch("src.store.os.replace", side_effect=OSError("replace failed")):
        with pytest.raises(OSError):
            store.mark_seen([_job(2)])

    assert path.read_text() == original
    assert json.loads(path.read_text())["seen"] == [
        "https://example.com/jobs/1?source=bot"
    ]


class _TelegramResponse:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


@pytest.fixture
def notifier(monkeypatch):
    monkeypatch.setenv("TELEGRAM_TOKEN", "secret-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "secret-chat")
    return TelegramNotifier()


@pytest.mark.parametrize(
    "response, expected",
    [
        (_TelegramResponse(200, {"ok": True}), None),
        (_TelegramResponse(500, {"ok": False}), "HTTP failure"),
        (_TelegramResponse(200, {"ok": False}), "did not acknowledge"),
        (_TelegramResponse(200, ValueError("bad json")), "malformed"),
    ],
)
def test_notifier_requires_explicit_acknowledgement(notifier, response, expected):
    with patch("src.notifier.requests.post", return_value=response) as post:
        if expected is None:
            notifier.send_message("hello")
        else:
            with pytest.raises(RuntimeError, match=expected):
                notifier.send_message("hello")
        assert post.call_count == 1


def test_notifier_transport_failure_is_surfaced_without_retry(notifier):
    with patch(
        "src.notifier.requests.post",
        side_effect=requests.Timeout("timed out"),
    ) as post:
        with pytest.raises(RuntimeError, match="transport failure"):
            notifier.send_message("hello")
    assert post.call_count == 1


def test_notifier_rejects_oversized_message_before_network(notifier):
    message = "🚀" * MAX_MESSAGE_LEN
    with patch("src.notifier.requests.post") as post:
        with pytest.raises(ValueError, match="exceeds"):
            notifier.send_message(message)
    post.assert_not_called()
