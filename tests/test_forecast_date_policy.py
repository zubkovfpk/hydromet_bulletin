import configparser
from datetime import datetime, timezone
from pathlib import Path

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
    )
    assert result == "20260420"


def test_no_date_uses_today_when_cmems_exists_morning(monkeypatch):
    today = datetime.now(timezone.utc).date().strftime("%Y%m%d")

    def _fake_discover(*, base_dir, run_date, cmems_storage_subdir, legacy_waves_dir):
        if run_date == today:
            return [Path("today.nc")], ["today"]
        return [], ["none"]

    monkeypatch.setattr(forecast_morning, "_discover_cmems_nc_files", _fake_discover)
    result = forecast_morning._resolve_run_date_for_dry_run(
        explicit_run_date=None,
        base_dir=".",
        cmems_storage_subdir="data/storage/cmems",
    )
    assert result == today


def test_no_date_falls_back_to_today_minus_1_morning(monkeypatch):
    today = datetime.now(timezone.utc).date()
    today_str = today.strftime("%Y%m%d")
    prev_str = (today - forecast_morning.timedelta(days=1)).strftime("%Y%m%d")

    def _fake_discover(*, base_dir, run_date, cmems_storage_subdir, legacy_waves_dir):
        if run_date == today_str:
            return [], ["today-empty"]
        if run_date == prev_str:
            return [Path("prev.nc")], ["prev-ok"]
        return [], ["none"]

    monkeypatch.setattr(forecast_morning, "_discover_cmems_nc_files", _fake_discover)
    result = forecast_morning._resolve_run_date_for_dry_run(
        explicit_run_date=None,
        base_dir=".",
        cmems_storage_subdir="data/storage/cmems",
    )
    assert result == prev_str


def test_no_date_raises_when_today_and_prev_missing_morning(monkeypatch):
    def _fake_discover(*, base_dir, run_date, cmems_storage_subdir, legacy_waves_dir):
        return [], ["none"]

    monkeypatch.setattr(forecast_morning, "_discover_cmems_nc_files", _fake_discover)
    with pytest.raises(FileNotFoundError, match="today UTC nor today-1"):
        forecast_morning._resolve_run_date_for_dry_run(
            explicit_run_date=None,
            base_dir=".",
            cmems_storage_subdir="data/storage/cmems",
        )


def test_cli_forecast_hours_override_priority_morning():
    cfg = _cfg_with_forecast_hours(120)
    assert forecast_morning._resolve_effective_forecast_hours(cfg, 48) == 48


def test_cli_forecast_hours_override_priority_evening():
    cfg = _cfg_with_forecast_hours(120)
    assert forecast_evening._resolve_effective_forecast_hours(cfg, 48) == 48

