"""Tests for DT-17-1: on-demand polling loop in forecast_main."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import forecast_main

UTC = timezone.utc
CYCLE = datetime(2026, 5, 14, 12, tzinfo=UTC)
CYCLE_STR = "2026-05-14T12Z"


def _write_manifest(path: Path, cycle_str: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "schema_version": "1.0",
        "updated_at": "2026-05-14T16:00:00+00:00",
        "gfs": {
            "latest_successful_cycle": cycle_str,
            "latest_successful_fetched_at": "2026-05-14T16:00:00+00:00",
            "latest_successful_source_timestamp": None,
            "storage_root": "data/storage",
            "relative_path": "gfs/20260514/12z/",
            "archive_slots": {"24h-back": None, "48h-back": None},
        },
        "cmems": None,
    }
    path.write_text(json.dumps(data))


def test_manifest_already_ready_skips_ingest(tmp_path, monkeypatch):
    """If manifest is already ready, _poll_until_ready returns None immediately."""
    manifest_path = tmp_path / "storage" / "manifest.json"
    _write_manifest(manifest_path, CYCLE_STR)
    monkeypatch.setattr(forecast_main, "MANIFEST_PATH", manifest_path)

    triggered = []
    monkeypatch.setattr(
        forecast_main,
        "_trigger_ingest",
        lambda *a, **kw: triggered.append(1) or MagicMock(),
    )

    result = forecast_main._poll_until_ready(
        effective_gfs_cycle=CYCLE,
        timeout_minutes=1,
        polling_minutes=1,
        no_ingest=False,
        logger=logging.getLogger("test"),
    )
    assert result is None
    assert len(triggered) == 0, "ingest should not be triggered if manifest ready"


def test_no_ingest_flag_skips_subprocess(tmp_path, monkeypatch):
    """--no-ingest: never calls _trigger_ingest even when manifest is stale."""
    manifest_path = tmp_path / "storage" / "manifest.json"
    _write_manifest(manifest_path, "2026-05-14T06Z")
    monkeypatch.setattr(forecast_main, "MANIFEST_PATH", manifest_path)

    triggered = []
    monkeypatch.setattr(
        forecast_main,
        "_trigger_ingest",
        lambda *a, **kw: triggered.append(1) or MagicMock(),
    )

    monkeypatch.setattr(forecast_main.time, "sleep", lambda s: None)
    monkeypatch.setattr(forecast_main.time, "monotonic", lambda: 0.0)

    result = forecast_main._poll_until_ready(
        effective_gfs_cycle=CYCLE,
        timeout_minutes=0,
        polling_minutes=1,
        no_ingest=True,
        logger=logging.getLogger("test"),
    )
    assert result == forecast_main.EXIT_TIMEOUT
    assert len(triggered) == 0


def test_ingest_triggered_when_manifest_stale(tmp_path, monkeypatch):
    """When manifest is stale, _trigger_ingest is called once."""
    manifest_path = tmp_path / "storage" / "manifest.json"
    _write_manifest(manifest_path, "2026-05-14T06Z")
    monkeypatch.setattr(forecast_main, "MANIFEST_PATH", manifest_path)

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mock_proc.returncode = None
    triggered = []

    def fake_trigger(cycle, logger):
        triggered.append(cycle)
        return mock_proc

    monkeypatch.setattr(forecast_main, "_trigger_ingest", fake_trigger)

    monkeypatch.setattr(forecast_main.time, "sleep", lambda s: None)
    monkeypatch.setattr(forecast_main.time, "monotonic", lambda: 0.0)

    result = forecast_main._poll_until_ready(
        effective_gfs_cycle=CYCLE,
        timeout_minutes=0,
        polling_minutes=1,
        no_ingest=False,
        logger=logging.getLogger("test"),
    )
    assert result == forecast_main.EXIT_TIMEOUT
    assert len(triggered) == 1, "ingest should be triggered once"


def test_poll_returns_none_when_manifest_updates(tmp_path, monkeypatch):
    """After ingest, manifest becomes ready during polling → return None."""
    manifest_path = tmp_path / "storage" / "manifest.json"
    _write_manifest(manifest_path, "2026-05-14T06Z")
    monkeypatch.setattr(forecast_main, "MANIFEST_PATH", manifest_path)

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mock_proc.wait.return_value = 0
    monkeypatch.setattr(forecast_main, "_trigger_ingest", lambda *a, **kw: mock_proc)

    call_count = [0]
    original_read = forecast_main._read_manifest_for_run

    def fake_read(path, **kwargs):
        call_count[0] += 1
        if call_count[0] >= 2:
            _write_manifest(manifest_path, CYCLE_STR)
        return original_read(path, **kwargs)

    monkeypatch.setattr(forecast_main, "_read_manifest_for_run", fake_read)

    mono_values = iter([0.0, 0.0, 100.0, 200.0, 300.0])
    monkeypatch.setattr(forecast_main.time, "sleep", lambda s: None)
    monkeypatch.setattr(forecast_main.time, "monotonic", lambda: next(mono_values))

    result = forecast_main._poll_until_ready(
        effective_gfs_cycle=CYCLE,
        timeout_minutes=5,
        polling_minutes=1,
        no_ingest=False,
        logger=logging.getLogger("test"),
    )
    assert result is None
