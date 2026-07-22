import json
from pathlib import Path

import pytest

from models import Job
from src.store import SeenStore


def _job(url: str, title: str = "Engineer") -> Job:
    return Job(
        id="1",
        title=title,
        company="Acme",
        location="Bangalore",
        url=url,
    )


@pytest.fixture
def store(tmp_path: Path) -> SeenStore:
    return SeenStore(tmp_path / "seen.json")


# ── filter_new ────────────────────────────────────────────────────────────────

def test_all_jobs_new_on_empty_store(store):
    jobs = [_job("https://example.com/jobs/1"), _job("https://example.com/jobs/2")]
    assert store.filter_new(jobs) == jobs


def test_filter_new_excludes_seen_job(store):
    job = _job("https://example.com/jobs/1")
    store.mark_seen([job])
    assert store.filter_new([job]) == []


def test_filter_new_returns_only_unseen(store):
    seen = _job("https://example.com/jobs/1")
    new = _job("https://example.com/jobs/2")
    store.mark_seen([seen])
    result = store.filter_new([seen, new])
    assert result == [new]


# ── mark_seen + persistence ───────────────────────────────────────────────────

def test_mark_seen_persists_to_disk(tmp_path):
    path = tmp_path / "seen.json"
    job = _job("https://example.com/jobs/1")

    store1 = SeenStore(path)
    store1.mark_seen([job])

    # A fresh store loaded from the same file should recognise the job.
    store2 = SeenStore(path)
    assert store2.filter_new([job]) == []


def test_seen_file_is_valid_json(tmp_path):
    path = tmp_path / "seen.json"
    store = SeenStore(path)
    store.mark_seen([_job("https://example.com/jobs/1")])

    data = json.loads(path.read_text())
    assert "seen" in data
    assert isinstance(data["seen"], list)


def test_count_reflects_marked_jobs(store):
    assert store.count == 0
    store.mark_seen([_job("https://example.com/jobs/1"), _job("https://example.com/jobs/2")])
    assert store.count == 2


def test_marking_same_job_twice_does_not_duplicate(store):
    job = _job("https://example.com/jobs/1")
    store.mark_seen([job])
    store.mark_seen([job])
    assert store.count == 1


def test_missing_file_treated_as_empty_store(tmp_path):
    store = SeenStore(tmp_path / "nonexistent.json")
    jobs = [_job("https://example.com/jobs/1")]
    assert store.filter_new(jobs) == jobs
