from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
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


def test_run_ingest_success_writes_manifest_and_rotates_archive(monkeypatch, tmp_path):
    events: list[dict[str, Any]] = []
    write_calls: list[tuple[Path, dict[str, Any]]] = []
    rotate_calls: list[dict[str, Any]] = []
    target_cycle = datetime(2026, 5, 13, 12, tzinfo=timezone.utc)
    slot_path = _patch_ingest_paths(monkeypatch, tmp_path, target_cycle)
    monkeypatch.setattr(ingest_gfs, "log_event", lambda **kwargs: events.append(kwargs))
    monkeypatch.setattr(ingest_gfs.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(ingest_gfs, "read_manifest", lambda path: _manifest(None))
    monkeypatch.setattr(ingest_gfs, "_attempt_download", lambda *args, **kwargs: ("success", 200, 123))
    _make_non_empty_dir(slot_path)

    def fake_rotate_archive(**kwargs):
        rotate_calls.append(kwargs)
        return {"24h-back": Path("a"), "48h-back": None}

    def fake_write_manifest(path, data):
        write_calls.append((Path(path), data))

    monkeypatch.setattr(ingest_gfs, "rotate_archive", fake_rotate_archive)
    monkeypatch.setattr(ingest_gfs, "write_manifest", fake_write_manifest)

    exit_code = ingest_gfs.run_ingest(
        target_cycle,
        max_retries=3,
        retry_interval_min=0,
        force=False,
        dry_run=False,
        logger=_logger(),
    )

    assert exit_code == 0
    assert len(rotate_calls) == 1
    assert rotate_calls[0]["source"] == "gfs"
    assert rotate_calls[0]["current_storage_path"] == slot_path
    assert len(write_calls) == 1
    written_manifest = write_calls[0][1]
    assert written_manifest["gfs"]["latest_successful_cycle"] == "2026-05-13T12Z"
    expected_parent = str(ingest_gfs.STORAGE_GFS_ROOT.parent).replace("\\", "/").rstrip("/")
    assert written_manifest["gfs"]["storage_root"] == expected_parent
    assert written_manifest["gfs"]["relative_path"] == "gfs/20260513/12z/"
    assert set(written_manifest["gfs"]["archive_slots"]["24h-back"]) == {"path", "archived_at"}
    assert [(event["event"], event["result"]) for event in events] == [
        ("poll_attempt", "success"),
        ("archive_rotation", "success"),
        ("manifest_update", "success"),
        ("ingest_complete", "success"),
    ]


def test_run_ingest_success_but_storage_path_missing_returns_2(monkeypatch, tmp_path):
    events: list[dict[str, Any]] = []
    rotate_calls: list[Any] = []
    write_calls: list[Any] = []
    target_cycle = datetime(2026, 5, 13, 12, tzinfo=timezone.utc)
    _patch_ingest_paths(monkeypatch, tmp_path, target_cycle)
    monkeypatch.setattr(ingest_gfs, "read_manifest", lambda path: _manifest(None))
    monkeypatch.setattr(ingest_gfs, "log_event", lambda **kwargs: events.append(kwargs))
    monkeypatch.setattr(ingest_gfs, "_attempt_download", lambda *args, **kwargs: ("success", 200, 50))
    monkeypatch.setattr(ingest_gfs, "rotate_archive", lambda *args, **kwargs: rotate_calls.append((args, kwargs)))
    monkeypatch.setattr(ingest_gfs, "write_manifest", lambda *args, **kwargs: write_calls.append((args, kwargs)))

    exit_code = ingest_gfs.run_ingest(
        target_cycle,
        max_retries=1,
        retry_interval_min=0,
        force=False,
        dry_run=False,
        logger=_logger(),
    )

    assert exit_code == 2
    assert rotate_calls == []
    assert write_calls == []
    assert events[-1]["event"] == "ingest_failed"
    assert events[-1]["result"] == "storage_path_missing"


def test_run_ingest_rotation_error_returns_2(monkeypatch, tmp_path):
    events: list[dict[str, Any]] = []
    write_calls: list[Any] = []
    target_cycle = datetime(2026, 5, 13, 12, tzinfo=timezone.utc)
    slot_path = _patch_ingest_paths(monkeypatch, tmp_path, target_cycle)
    _make_non_empty_dir(slot_path)
    monkeypatch.setattr(ingest_gfs, "read_manifest", lambda path: _manifest(None))
    monkeypatch.setattr(ingest_gfs, "log_event", lambda **kwargs: events.append(kwargs))
    monkeypatch.setattr(ingest_gfs, "_attempt_download", lambda *args, **kwargs: ("success", 200, 50))
    monkeypatch.setattr(ingest_gfs, "write_manifest", lambda *args, **kwargs: write_calls.append((args, kwargs)))

    def fail_rotate_archive(**kwargs):
        raise ingest_gfs.ArchiveRotationError("3+ slots")

    monkeypatch.setattr(ingest_gfs, "rotate_archive", fail_rotate_archive)

    exit_code = ingest_gfs.run_ingest(
        target_cycle,
        max_retries=1,
        retry_interval_min=0,
        force=False,
        dry_run=False,
        logger=_logger(),
    )

    rotation_events = [event for event in events if event["event"] == "archive_rotation"]
    assert exit_code == 2
    assert write_calls == []
    assert rotation_events[-1]["result"] == "rotation_error"
    assert "3+ slots" in rotation_events[-1]["error_message"]


def test_run_ingest_manifest_corrupted_on_final_read_returns_2(monkeypatch, tmp_path):
    events: list[dict[str, Any]] = []
    write_calls: list[Any] = []
    rotate_calls: list[Any] = []
    target_cycle = datetime(2026, 5, 13, 12, tzinfo=timezone.utc)
    slot_path = _patch_ingest_paths(monkeypatch, tmp_path, target_cycle)
    _make_non_empty_dir(slot_path)
    manifests: list[dict[str, Any] | Exception] = [
        _manifest(None),
        ingest_gfs.ManifestCorruptedError("bad manifest"),
    ]
    monkeypatch.setattr(ingest_gfs, "log_event", lambda **kwargs: events.append(kwargs))
    monkeypatch.setattr(ingest_gfs, "_attempt_download", lambda *args, **kwargs: ("success", 200, 50))
    monkeypatch.setattr(ingest_gfs, "write_manifest", lambda *args, **kwargs: write_calls.append((args, kwargs)))

    def fake_read_manifest(path):
        value = manifests.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    def fake_rotate_archive(**kwargs):
        rotate_calls.append(kwargs)
        return {"24h-back": Path("a"), "48h-back": None}

    monkeypatch.setattr(ingest_gfs, "read_manifest", fake_read_manifest)
    monkeypatch.setattr(ingest_gfs, "rotate_archive", fake_rotate_archive)

    exit_code = ingest_gfs.run_ingest(
        target_cycle,
        max_retries=1,
        retry_interval_min=0,
        force=False,
        dry_run=False,
        logger=_logger(),
    )

    manifest_events = [event for event in events if event["event"] == "manifest_update"]
    assert exit_code == 2
    assert len(rotate_calls) == 1
    assert write_calls == []
    assert manifest_events[-1]["result"] == "parse_error"


def test_run_ingest_write_manifest_value_error_returns_2(monkeypatch, tmp_path):
    events: list[dict[str, Any]] = []
    target_cycle = datetime(2026, 5, 13, 12, tzinfo=timezone.utc)
    slot_path = _patch_ingest_paths(monkeypatch, tmp_path, target_cycle)
    _make_non_empty_dir(slot_path)
    monkeypatch.setattr(ingest_gfs, "read_manifest", lambda path: _manifest(None))
    monkeypatch.setattr(ingest_gfs, "log_event", lambda **kwargs: events.append(kwargs))
    monkeypatch.setattr(ingest_gfs, "_attempt_download", lambda *args, **kwargs: ("success", 200, 50))
    monkeypatch.setattr(
        ingest_gfs,
        "rotate_archive",
        lambda **kwargs: {"24h-back": Path("a"), "48h-back": None},
    )

    def fail_write_manifest(path, data):
        raise ValueError("schema_version invalid")

    monkeypatch.setattr(ingest_gfs, "write_manifest", fail_write_manifest)

    exit_code = ingest_gfs.run_ingest(
        target_cycle,
        max_retries=1,
        retry_interval_min=0,
        force=False,
        dry_run=False,
        logger=_logger(),
    )

    manifest_events = [event for event in events if event["event"] == "manifest_update"]
    assert exit_code == 2
    assert manifest_events[-1]["result"] == "parse_error"
    assert "schema_version" in manifest_events[-1]["error_message"]


def test_run_ingest_success_event_replaces_stub(monkeypatch, tmp_path):
    events: list[dict[str, Any]] = []
    target_cycle = datetime(2026, 5, 13, 12, tzinfo=timezone.utc)
    slot_path = _patch_ingest_paths(monkeypatch, tmp_path, target_cycle)
    _make_non_empty_dir(slot_path)
    monkeypatch.setattr(ingest_gfs, "read_manifest", lambda path: _manifest(None))
    monkeypatch.setattr(ingest_gfs, "log_event", lambda **kwargs: events.append(kwargs))
    monkeypatch.setattr(ingest_gfs, "_attempt_download", lambda *args, **kwargs: ("success", 200, 50))
    monkeypatch.setattr(
        ingest_gfs,
        "rotate_archive",
        lambda **kwargs: {"24h-back": Path("a"), "48h-back": None},
    )
    monkeypatch.setattr(ingest_gfs, "write_manifest", lambda path, data: None)

    exit_code = ingest_gfs.run_ingest(
        target_cycle,
        max_retries=1,
        retry_interval_min=0,
        force=False,
        dry_run=False,
        logger=_logger(),
    )

    event_names = [event["event"] for event in events]
    assert exit_code == 0
    assert "ingest_complete" in event_names
    assert "ingest_complete_stub" not in event_names


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


def test_main_unhandled_exception_log_event_failure_still_returns_2(monkeypatch, tmp_path, caplog):
    monkeypatch.chdir(tmp_path)
    test_logger = logging.getLogger("test_ingest_gfs_safe_error")
    test_logger.handlers.clear()
    test_logger.propagate = True
    monkeypatch.setattr(ingest_gfs, "_build_logger", lambda: test_logger)

    def fail_run_ingest(*args, **kwargs):
        raise RuntimeError("boom")

    def fail_log_event(**kwargs):
        raise RuntimeError("event log not writable")

    monkeypatch.setattr(ingest_gfs, "run_ingest", fail_run_ingest)
    monkeypatch.setattr(ingest_gfs, "log_event", fail_log_event)
    caplog.set_level(logging.WARNING, logger="test_ingest_gfs_safe_error")

    exit_code = ingest_gfs.main(["--cycle", "2026-05-13T12Z"])

    assert exit_code == 2
    assert "failed to log ingest_failed event" in caplog.text
    assert "boom" in caplog.text


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
            "storage_root": "storage/gfs",
            "relative_path": "gfs/20260513/12z/",
            "archive_slots": {"24h-back": None, "48h-back": None},
        },
        "cmems": None,
    }


def _patch_ingest_paths(monkeypatch, tmp_path: Path, cycle_dt: datetime) -> Path:
    storage_root = tmp_path / "storage" / "gfs"
    monkeypatch.setattr(ingest_gfs, "STORAGE_GFS_ROOT", storage_root)
    monkeypatch.setattr(ingest_gfs, "ARCHIVE_GFS_ROOT", tmp_path / "storage" / "archive" / "gfs")
    monkeypatch.setattr(ingest_gfs, "MANIFEST_PATH", tmp_path / "storage" / "manifest.json")
    return storage_root / cycle_dt.strftime("%Y%m%d") / f"{cycle_dt:%H}z"


def _make_non_empty_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "marker.txt").write_text("data", encoding="utf-8")


def _logger() -> logging.Logger:
    logger = logging.getLogger("test_ingest_gfs_cli")
    logger.handlers.clear()
    logger.addHandler(logging.NullHandler())
    return logger
