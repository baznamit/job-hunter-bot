import json

from src.recovery_store import (
    RecoveryStore,
)


def test_recovery_allowed_initially(
    tmp_path,
):
    store = RecoveryStore(
        tmp_path / "recovery.json"
    )

    allowed, retry_at = (
        store.should_attempt(
            "phonepe"
        )
    )

    assert allowed is True
    assert retry_at is None


def test_failure_creates_cooldown(
    tmp_path,
):
    path = (
        tmp_path
        / "recovery.json"
    )

    store = RecoveryStore(
        path
    )

    store.record_failure(
        "phonepe",
        base_hours=6,
        max_hours=72,
    )

    allowed, retry_at = (
        store.should_attempt(
            "phonepe"
        )
    )

    assert allowed is False
    assert retry_at is not None

    data = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    assert (
        data["phonepe"]["failures"]
        == 1
    )


def test_clear_removes_cooldown(
    tmp_path,
):
    store = RecoveryStore(
        tmp_path / "recovery.json"
    )

    store.record_failure(
        "phonepe",
        base_hours=6,
        max_hours=72,
    )

    store.clear(
        "phonepe"
    )

    allowed, retry_at = (
        store.should_attempt(
            "phonepe"
        )
    )

    assert allowed is True
    assert retry_at is None


def test_failure_count_increases(
    tmp_path,
):
    path = (
        tmp_path
        / "recovery.json"
    )

    store = RecoveryStore(
        path
    )

    store.record_failure(
        "phonepe",
        base_hours=6,
        max_hours=72,
    )

    store.record_failure(
        "phonepe",
        base_hours=6,
        max_hours=72,
    )

    data = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    assert (
        data["phonepe"]["failures"]
        == 2
    )
