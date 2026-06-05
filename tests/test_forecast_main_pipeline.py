from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np

import forecast_main


def test_dry_run_does_not_call_pipeline(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    calls = _patch_pipeline(monkeypatch)

    exit_code = forecast_main.main(
        ["--date", "2026-05-14", "--time", "18:00", "--tz", "MSK", "--dry-run"]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert calls == {"meteo": 0, "wave": 0, "validate": 0, "temp": 0, "wind": 0, "precip": 0, "doc": 0}
    assert "output_filename:" in captured.out
    assert "[dry-run] pipeline plan:" in captured.out


def test_dry_run_does_not_create_output_dir(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _patch_pipeline(monkeypatch)

    exit_code = forecast_main.main(
        ["--date", "2026-05-14", "--time", "18:00", "--tz", "MSK", "--dry-run"]
    )

    assert exit_code == 0
    assert not (tmp_path / "output").exists()


def test_real_run_creates_docx_file(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _patch_pipeline(monkeypatch)

    exit_code = forecast_main.main(["--date", "2026-05-14", "--time", "18:00", "--tz", "MSK", "--no-email"])

    output_path = tmp_path / "output" / "Прогноз_20260514_1800.docx"
    assert exit_code == 0
    assert output_path.exists()


def test_real_run_force_overwrites_existing_docx(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _patch_pipeline(monkeypatch, doc_content=b"new")
    output_path = tmp_path / "output" / "Прогноз_20260514_1800.docx"
    output_path.parent.mkdir(parents=True)
    output_path.write_bytes(b"old")

    exit_code = forecast_main.main(
        ["--date", "2026-05-14", "--time", "18:00", "--tz", "MSK", "--force", "--no-email"]
    )

    assert exit_code == 0
    assert output_path.exists()
    assert output_path.read_bytes() == b"new"


def test_real_run_collision_without_force_uses_req_suffix(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _patch_pipeline(monkeypatch)
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "Прогноз_20260514_1800.docx").write_bytes(b"existing")

    exit_code = forecast_main.main(["--date", "2026-05-14", "--time", "18:00", "--tz", "MSK", "--no-email"])

    matches = list(output_dir.glob("Прогноз_20260514_1800_req-*.docx"))
    assert exit_code == 0
    assert len(matches) == 1


def test_no_email_flag_accepted(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    _patch_pipeline(monkeypatch)

    exit_code = forecast_main.main(
        ["--date", "2026-05-14", "--time", "18:00", "--tz", "MSK", "--dry-run", "--no-email"]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "email: skipped (dry-run; email layer not invoked)" in captured.out


def test_unknown_exception_returns_1(monkeypatch, tmp_path, caplog):
    monkeypatch.chdir(tmp_path)
    _patch_pipeline(monkeypatch, doc_error=RuntimeError("boom"))
    caplog.set_level(logging.ERROR)

    exit_code = forecast_main.main(["--date", "2026-05-14", "--time", "18:00", "--tz", "MSK", "--no-email"])

    assert exit_code == 10
    assert "RuntimeError: boom" in caplog.text or "boom" in caplog.text


def test_manifest_paths_logged_when_present(monkeypatch, tmp_path, caplog):
    monkeypatch.chdir(tmp_path)
    _patch_pipeline(monkeypatch)
    _write_manifest(
        tmp_path / "storage" / "manifest.json",
        gfs_cycle="2026-05-14T12Z",
        gfs_storage_root="storage",
        gfs_relative_path="gfs/20260514/12z/",
    )
    caplog.set_level(logging.INFO)

    (tmp_path / "storage" / "gfs" / "20260514" / "12z").mkdir(parents=True)

    # 18:00 MSK → floor 06Z (lag 6h); manifest 12Z → info log
    exit_code = forecast_main.main(["--date", "2026-05-14", "--time", "18:00", "--tz", "MSK", "--no-email"])

    assert exit_code == 0
    assert "using GFS storage from manifest: storage / gfs/20260514/12z/" in caplog.text
    assert "using GFS cycle from manifest:" in caplog.text


def test_manifest_cycle_used_over_floor(monkeypatch, tmp_path, caplog):
    """manifest cycle (12Z) takes priority over floor cycle (06Z)."""
    monkeypatch.chdir(tmp_path)
    _patch_pipeline(monkeypatch)
    _write_manifest(
        tmp_path / "storage" / "manifest.json",
        gfs_cycle="2026-05-14T12Z",
        gfs_storage_root="storage",
        gfs_relative_path="gfs/20260514/12z/",
    )
    (tmp_path / "storage" / "gfs" / "20260514" / "12z").mkdir(parents=True)
    caplog.set_level(logging.INFO)

    exit_code = forecast_main.main(
        ["--date", "2026-05-14", "--time", "09:01", "--tz", "UTC", "--no-email"]
    )

    assert exit_code == 0
    assert "using GFS cycle from manifest: 2026-05-14T12Z" in caplog.text


def test_manifest_cycle_mismatch_logs_warning(monkeypatch, tmp_path, caplog):
    monkeypatch.chdir(tmp_path)
    _patch_pipeline(monkeypatch)
    _write_manifest(
        tmp_path / "storage" / "manifest.json",
        gfs_cycle="2026-05-13T12Z",
        gfs_storage_root="storage",
        gfs_relative_path="gfs/20260513/12z/",
    )
    caplog.set_level(logging.INFO)

    (tmp_path / "storage" / "gfs" / "20260513" / "12z").mkdir(parents=True)

    exit_code = forecast_main.main(["--date", "2026-05-14", "--time", "18:00", "--tz", "MSK", "--no-email"])

    assert exit_code == 0
    assert "using GFS cycle from manifest: 2026-05-13T12Z" in caplog.text


def test_manifest_missing_does_not_warn(monkeypatch, tmp_path, caplog):
    monkeypatch.chdir(tmp_path)
    calls = _patch_pipeline(monkeypatch)
    caplog.set_level(logging.INFO)

    exit_code = forecast_main.main(["--date", "2026-05-14", "--time", "18:00", "--tz", "MSK", "--no-email"])

    assert exit_code == 0
    assert calls["doc"] == 1
    assert "using GFS storage from manifest:" not in caplog.text
    assert "manifest GFS cycle != resolved cycle" not in caplog.text


def _patch_pipeline(monkeypatch, *, doc_content: bytes = b"\x00", doc_error: Exception | None = None) -> dict[str, int]:
    calls = {"meteo": 0, "wave": 0, "validate": 0, "temp": 0, "wind": 0, "precip": 0, "doc": 0}

    def fake_collect_meteo_data(*args: Any, **kwargs: Any) -> dict[str, np.ndarray]:
        calls["meteo"] += 1
        return _fake_meteo()

    def fake_collect_wave_data(*args: Any, **kwargs: Any) -> tuple[np.ndarray, datetime, datetime]:
        calls["wave"] += 1
        start = datetime(2026, 5, 14, tzinfo=timezone.utc)
        return np.ones((2, 2, 1)), start, start

    def fake_assert_valid_for_bulletin(*args: Any, **kwargs: Any) -> None:
        calls["validate"] += 1

    def fake_temp_statistics(*args: Any, **kwargs: Any) -> str:
        calls["temp"] += 1
        return "Температура воздуха 10...12 °С."

    def fake_wind_statistics(*args: Any, **kwargs: Any) -> tuple[str, float, float]:
        calls["wind"] += 1
        return "северный", 1.0, 2.0

    def fake_precip_statistics(*args: Any, **kwargs: Any) -> str:
        calls["precip"] += 1
        return "Без осадков."

    def fake_build_doc(*args: Any, **kwargs: Any) -> str:
        calls["doc"] += 1
        if doc_error is not None:
            raise doc_error
        output_path = Path(kwargs["output_path"])
        output_path.write_bytes(doc_content)
        return str(output_path)

    monkeypatch.setattr(forecast_main, "_poll_until_ready", lambda **kwargs: None)
    monkeypatch.setattr(forecast_main, "collect_meteo_data", fake_collect_meteo_data)
    monkeypatch.setattr(forecast_main, "collect_wave_data", fake_collect_wave_data)
    monkeypatch.setattr(forecast_main, "assert_valid_for_bulletin", fake_assert_valid_for_bulletin)
    monkeypatch.setattr(forecast_main, "temp_statistics", fake_temp_statistics)
    monkeypatch.setattr(forecast_main, "wind_statistics", fake_wind_statistics)
    monkeypatch.setattr(forecast_main, "precip_statistics", fake_precip_statistics)
    monkeypatch.setattr(forecast_main, "build_doc", fake_build_doc)
    return calls


def _fake_meteo() -> dict[str, np.ndarray]:
    daily = np.ones((2, 2, 1))
    return {
        "Temp": np.ones((2, 2, 2)) * 10.0,
        "Rain": daily,
        "Freeze_Rain": daily,
        "Ice_Pell": daily,
        "Snow": daily,
        "Wind_Gust": daily * 5.0,
        "U_wind": daily,
        "V_wind": daily,
        "Vis": daily * 10_000.0,
    }


def _write_manifest(path: Path, *, gfs_cycle: str, gfs_storage_root: str, gfs_relative_path: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1.0",
        "updated_at": "2026-05-14T00:00:00+00:00",
        "gfs": {
            "latest_successful_cycle": gfs_cycle,
            "latest_successful_fetched_at": "2026-05-14T08:00:00+00:00",
            "latest_successful_source_timestamp": None,
            "storage_root": gfs_storage_root,
            "relative_path": gfs_relative_path,
            "archive_slots": {"24h-back": None, "48h-back": None},
        },
        "cmems": None,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
