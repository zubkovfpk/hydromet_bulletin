import configparser
from datetime import datetime, timezone

import pytest

import forecast_evening
import forecast_morning


def _cfg_with_forecast_hours(hours: int = 120) -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    cfg.read_dict({"CMEMS_FORECAST": {"forecast_hours": str(hours)}})
    return cfg


def test_explicit_date_disables_fallback_morning():
    result = forecast_morning._resolve_run_date_for_dry_run(
        explicit_run_date="20260420",
        base_dir=".",
        cmems_storage_subdir="data/storage/cmems",
        gfs_storage_subdir="data/storage/gfs",
        gfs_cycle="00z",
    )
    assert result == "20260420"


def test_no_date_uses_today_when_cmems_exists_morning(monkeypatch):
    today = datetime.now(timezone.utc).date().strftime("%Y%m%d")

    def _fake_has_cmems_for_date(*, base_dir, run_date, cmems_storage_subdir):
        return run_date == today

    def _fake_has_gfs_for_date(*, base_dir, run_date, gfs_storage_subdir, gfs_cycle):
        return run_date == today

    monkeypatch.setattr(forecast_morning, "has_cmems_for_date", _fake_has_cmems_for_date)
    monkeypatch.setattr(forecast_morning, "has_gfs_for_date", _fake_has_gfs_for_date)
    result = forecast_morning._resolve_run_date_for_dry_run(
        explicit_run_date=None,
        base_dir=".",
        cmems_storage_subdir="data/storage/cmems",
        gfs_storage_subdir="data/storage/gfs",
        gfs_cycle="00z",
    )
    assert result == today


def test_no_date_falls_back_to_today_minus_1_morning(monkeypatch):
    today = datetime.now(timezone.utc).date()
    today_str = today.strftime("%Y%m%d")
    prev_str = (today - forecast_morning.timedelta(days=1)).strftime("%Y%m%d")

    def _fake_has_cmems_for_date(*, base_dir, run_date, cmems_storage_subdir):
        return run_date in {today_str, prev_str}

    def _fake_has_gfs_for_date(*, base_dir, run_date, gfs_storage_subdir, gfs_cycle):
        return run_date == prev_str

    monkeypatch.setattr(forecast_morning, "has_cmems_for_date", _fake_has_cmems_for_date)
    monkeypatch.setattr(forecast_morning, "has_gfs_for_date", _fake_has_gfs_for_date)
    result = forecast_morning._resolve_run_date_for_dry_run(
        explicit_run_date=None,
        base_dir=".",
        cmems_storage_subdir="data/storage/cmems",
        gfs_storage_subdir="data/storage/gfs",
        gfs_cycle="00z",
    )
    assert result == prev_str


def test_no_date_raises_when_today_and_prev_missing_morning(monkeypatch):
    def _fake_has_cmems_for_date(*, base_dir, run_date, cmems_storage_subdir):
        return False

    def _fake_has_gfs_for_date(*, base_dir, run_date, gfs_storage_subdir, gfs_cycle):
        return False

    monkeypatch.setattr(forecast_morning, "has_cmems_for_date", _fake_has_cmems_for_date)
    monkeypatch.setattr(forecast_morning, "has_gfs_for_date", _fake_has_gfs_for_date)
    with pytest.raises(FileNotFoundError, match="today UTC nor today-1"):
        forecast_morning._resolve_run_date_for_dry_run(
            explicit_run_date=None,
            base_dir=".",
            cmems_storage_subdir="data/storage/cmems",
            gfs_storage_subdir="data/storage/gfs",
            gfs_cycle="00z",
        )


def test_cli_forecast_hours_override_priority_morning():
    cfg = _cfg_with_forecast_hours(120)
    assert forecast_morning._resolve_effective_forecast_hours(cfg, 48) == 48


def test_cli_forecast_hours_override_priority_evening():
    cfg = _cfg_with_forecast_hours(120)
    assert forecast_evening._resolve_effective_forecast_hours(cfg, 48) == 48

