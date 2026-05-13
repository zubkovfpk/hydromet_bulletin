from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import pytest

import ingest_gfs


def test_resolve_target_cycle_floor_no_override():
    cases = [
        (datetime(2026, 5, 13, 14, 37, 21, tzinfo=timezone.utc), datetime(2026, 5, 13, 12, tzinfo=timezone.utc)),
        (datetime(2026, 5, 13, 5, 59, tzinfo=timezone.utc), datetime(2026, 5, 13, 0, tzinfo=timezone.utc)),
        (datetime(2026, 5, 13, 6, 0, tzinfo=timezone.utc), datetime(2026, 5, 13, 6, tzinfo=timezone.utc)),
        (datetime(2026, 5, 13, 23, 59, tzinfo=timezone.utc), datetime(2026, 5, 13, 18, tzinfo=timezone.utc)),
    ]

    for now_utc, expected in cases:
        assert ingest_gfs.resolve_target_cycle(now_utc, None) == expected


def test_resolve_target_cycle_override_valid():
    assert ingest_gfs.resolve_target_cycle("ignored", "2026-05-13T06Z") == datetime(
        2026,
        5,
        13,
        6,
        tzinfo=timezone.utc,
    )


@pytest.mark.parametrize("override", ["2026-05-13T07Z", "2026-05-13T06"])
def test_resolve_target_cycle_override_rejects_bad_hour(override):
    with pytest.raises(ValueError):
        ingest_gfs.resolve_target_cycle(datetime(2026, 5, 13, 14, tzinfo=timezone.utc), override)


def test_run_ingest_skips_when_already_ingested(monkeypatch):
    events: list[dict[str, Any]] = []
    monkeypatch.setattr(ingest_gfs, "read_manifest", lambda path: _manifest("2026-05-13T12Z"))
    monkeypatch.setattr(ingest_gfs, "log_event", lambda **kwargs: events.append(kwargs))

    exit_code = ingest_gfs.run_ingest(
        datetime(2026, 5, 13, 12, tzinfo=timezone.utc),
        max_retries=3,
        retry_interval_min=0,
        force=False,
        dry_run=True,
        logger=_logger(),
    )

    assert exit_code == 0
    assert [event["event"] for event in events] == ["ingest_skip"]
    assert events[0]["result"] == "already_ingested"


def test_run_ingest_force_overrides_skip(monkeypatch):
    events: list[dict[str, Any]] = []
    attempts: list[datetime] = []
    monkeypatch.setattr(ingest_gfs, "read_manifest", lambda path: _manifest("2026-05-13T12Z"))
    monkeypatch.setattr(ingest_gfs, "log_event", lambda **kwargs: events.append(kwargs))
    monkeypatch.setattr(ingest_gfs.time, "sleep", lambda seconds: None)

    def fake_attempt(cycle_dt, *, dry_run, logger):
        attempts.append(cycle_dt)
        return "not_ready", 404, 10

    monkeypatch.setattr(ingest_gfs, "_attempt_download", fake_attempt)

    exit_code = ingest_gfs.run_ingest(
        datetime(2026, 5, 13, 12, tzinfo=timezone.utc),
        max_retries=1,
        retry_interval_min=0,
        force=True,
        dry_run=True,
        logger=_logger(),
    )

    assert exit_code == 2
    assert len(attempts) == 1
    assert events[0]["event"] == "poll_attempt"


def test_run_ingest_success_path_does_not_write_manifest(monkeypatch):
    events: list[dict[str, Any]] = []
    write_calls: list[Any] = []
    rotate_calls: list[Any] = []
    monkeypatch.setattr(ingest_gfs, "read_manifest", lambda path: _manifest(None))
    monkeypatch.setattr(ingest_gfs, "log_event", lambda **kwargs: events.append(kwargs))
    monkeypatch.setattr(ingest_gfs.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(ingest_gfs, "write_manifest", lambda *args, **kwargs: write_calls.append((args, kwargs)))
    monkeypatch.setattr(ingest_gfs, "rotate_archive", lambda *args, **kwargs: rotate_calls.append((args, kwargs)))
    monkeypatch.setattr(ingest_gfs, "_attempt_download", lambda *args, **kwargs: ("success", 200, 123))

    exit_code = ingest_gfs.run_ingest(
        datetime(2026, 5, 13, 12, tzinfo=timezone.utc),
        max_retries=3,
        retry_interval_min=0,
        force=False,
        dry_run=False,
        logger=_logger(),
    )

    complete_events = [event for event in events if event["event"] == "ingest_complete_stub"]
    assert exit_code == 0
    assert len(complete_events) == 1
    assert write_calls == []
    assert rotate_calls == []


def test_run_ingest_retries_then_exits_2(monkeypatch):
    events: list[dict[str, Any]] = []
    monkeypatch.setattr(ingest_gfs, "read_manifest", lambda path: _manifest(None))
    monkeypatch.setattr(ingest_gfs, "log_event", lambda **kwargs: events.append(kwargs))
    monkeypatch.setattr(ingest_gfs.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(ingest_gfs, "_attempt_download", lambda *args, **kwargs: ("not_ready", 404, 10))

    exit_code = ingest_gfs.run_ingest(
        datetime(2026, 5, 13, 12, tzinfo=timezone.utc),
        max_retries=3,
        retry_interval_min=0,
        force=False,
        dry_run=True,
        logger=_logger(),
    )

    poll_events = [event for event in events if event["event"] == "poll_attempt"]
    failed_events = [event for event in events if event["event"] == "ingest_failed"]
    assert exit_code == 2
    assert [event["retry_number"] for event in poll_events] == [1, 2, 3]
    assert len(failed_events) == 1
    assert failed_events[0]["result"] == "retries_exhausted"


def test_main_dry_run_uses_synthetic_attempt(monkeypatch, tmp_path, capsys):
    events: list[dict[str, Any]] = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ingest_gfs, "read_manifest", lambda path: _manifest(None))
    monkeypatch.setattr(ingest_gfs, "log_event", lambda **kwargs: events.append(kwargs))
    monkeypatch.setattr(ingest_gfs.time, "sleep", lambda seconds: None)

    exit_code = ingest_gfs.main(
        [
            "--dry-run",
            "--max-retries",
            "2",
            "--retry-interval-min",
            "0",
            "--cycle",
            "2026-05-13T12Z",
        ]
    )

    captured = capsys.readouterr()
    poll_events = [event for event in events if event["event"] == "poll_attempt"]
    assert exit_code == 2
    assert (tmp_path / "storage" / ".ingest_gfs.lock").exists()
    assert [event["result"] for event in poll_events] == ["not_ready", "not_ready"]
    assert [event["http_status"] for event in poll_events] == [404, 404]
    assert captured.err == ""


def test_main_unhandled_exception_returns_2(monkeypatch, tmp_path):
    events: list[dict[str, Any]] = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ingest_gfs, "log_event", lambda **kwargs: events.append(kwargs))

    def fail_run_ingest(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(ingest_gfs, "run_ingest", fail_run_ingest)

    exit_code = ingest_gfs.main(["--cycle", "2026-05-13T12Z"])

    assert exit_code == 2
    assert events == [
        {
            "source": "gfs",
            "event": "ingest_failed",
            "target_cycle": "2026-05-13T12Z",
            "result": "unhandled_exception",
            "error_message": "boom",
        }
    ]


def _manifest(latest_cycle: str | None) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "updated_at": "2026-05-13T12:00:00+00:00",
        "gfs": None
        if latest_cycle is None
        else {
            "latest_successful_cycle": latest_cycle,
            "latest_successful_fetched_at": "2026-05-13T16:42:18+00:00",
            "latest_successful_source_timestamp": "2026-05-13T12:00:00+00:00",
            "storage_path": "storage/gfs/20260513/12z/",
            "archive_slots": {"24h-back": None, "48h-back": None},
        },
        "cmems": None,
    }


def _logger() -> logging.Logger:
    logger = logging.getLogger("test_ingest_gfs_cli")
    logger.handlers.clear()
    logger.addHandler(logging.NullHandler())
    return logger
