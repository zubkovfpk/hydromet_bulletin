"""Tests for DT-16-4: strict-manifest mode in forecast_main."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import forecast_main

UTC = timezone.utc


def _manifest_with_cycle(cycle_str: str) -> dict:
    return {
        "schema_version": "1.0",
        "updated_at": "2026-05-14T12:00:00+00:00",
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


def test_strict_manifest_exits_2_when_gfs_block_missing(caplog, tmp_path):
    manifest = {
        "schema_version": "1.0",
        "updated_at": "2026-05-14T12:00:00+00:00",
        "gfs": None,
        "cmems": None,
    }
    logger = logging.getLogger("test_strict_no_gfs")
    resolved_utc = datetime(2026, 5, 14, 18, 0, tzinfo=UTC)
    result = forecast_main._check_strict_manifest(
        manifest=manifest,
        resolved_utc=resolved_utc,
        gfs_storage_path=None,
        logger=logger,
    )
    assert result == 2


def test_strict_manifest_exits_2_when_stale(caplog, tmp_path):
    manifest = _manifest_with_cycle("2026-05-14T00Z")
    logger = logging.getLogger("test_strict_stale")
    resolved_utc = datetime(2026, 5, 14, 8, 0, tzinfo=UTC)
    result = forecast_main._check_strict_manifest(
        manifest=manifest,
        resolved_utc=resolved_utc,
        gfs_storage_path=None,
        logger=logger,
    )
    assert result == 2


def test_strict_manifest_exits_2_when_path_missing(tmp_path):
    manifest = _manifest_with_cycle("2026-05-14T12Z")
    logger = logging.getLogger("test_strict_path")
    resolved_utc = datetime(2026, 5, 14, 13, 0, tzinfo=UTC)
    missing_path = tmp_path / "nonexistent" / "path"
    result = forecast_main._check_strict_manifest(
        manifest=manifest,
        resolved_utc=resolved_utc,
        gfs_storage_path=missing_path,
        logger=logger,
    )
    assert result == 2


def test_strict_manifest_returns_none_when_ok(tmp_path):
    manifest = _manifest_with_cycle("2026-05-14T12Z")
    logger = logging.getLogger("test_strict_ok")
    resolved_utc = datetime(2026, 5, 14, 13, 0, tzinfo=UTC)
    existing_path = tmp_path / "gfs" / "20260514" / "12z"
    existing_path.mkdir(parents=True)
    result = forecast_main._check_strict_manifest(
        manifest=manifest,
        resolved_utc=resolved_utc,
        gfs_storage_path=existing_path,
        logger=logger,
    )
    assert result is None
