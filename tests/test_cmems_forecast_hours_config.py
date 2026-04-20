import configparser
import logging

from utils.downloaders.cmems_downloader import resolve_cmems_forecast_hours


def _base_cfg() -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    cfg.read_dict({"CMEMS_FORECAST": {}})
    return cfg


def test_resolve_forecast_hours_prefers_forecast_hours(caplog):
    cfg = _base_cfg()
    cfg.set("CMEMS_FORECAST", "forecast_hours", "120")
    cfg.set("CMEMS_FORECAST", "forecast_days", "5")
    with caplog.at_level(logging.WARNING):
        result = resolve_cmems_forecast_hours(cfg)
    assert result == 120
    assert "deprecated" not in caplog.text


def test_resolve_forecast_hours_fallback_from_days_with_warning(caplog):
    cfg = _base_cfg()
    cfg.set("CMEMS_FORECAST", "forecast_days", "5")
    with caplog.at_level(logging.WARNING):
        result = resolve_cmems_forecast_hours(cfg)
    assert result == 120
    assert "forecast_days is deprecated" in caplog.text


def test_resolve_forecast_hours_default_when_missing(caplog):
    cfg = _base_cfg()
    with caplog.at_level(logging.WARNING):
        result = resolve_cmems_forecast_hours(cfg)
    assert result == 120
    assert "using default 120h" in caplog.text

