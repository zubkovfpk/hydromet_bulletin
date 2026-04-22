import pytest
from datetime import datetime
from zoneinfo import ZoneInfo

from forecast_main import (
    main,
    msk_to_utc,
    parse_args,
    resolve_cmems_layer,
    resolve_gfs_cycle,
)


@pytest.mark.parametrize(
    ("date_str", "time_str", "tz_name", "expected_utc_iso"),
    [
        ("2026-04-22", "18:00", "MSK", "2026-04-22T15:00:00+00:00"),
        ("2026-04-22", "00:30", "MSK", "2026-04-21T21:30:00+00:00"),
        ("2026-04-22", "23:30", "MSK", "2026-04-22T20:30:00+00:00"),
        ("2026-04-22", "12:00", "UTC", "2026-04-22T12:00:00+00:00"),
        ("2026-01-15", "12:00", "MSK", "2026-01-15T09:00:00+00:00"),
        ("2026-07-15", "12:00", "MSK", "2026-07-15T09:00:00+00:00"),
    ],
)
def test_msk_to_utc_cases(date_str, time_str, tz_name, expected_utc_iso):
    assert msk_to_utc(date_str, time_str, tz_name).isoformat() == expected_utc_iso


@pytest.mark.parametrize(
    ("date_str", "time_str", "tz_name"),
    [
        ("2026-13-01", "12:00", "MSK"),
        ("2026-04-22", "25:00", "MSK"),
        ("2026-04-22", "12:00", "PST"),
    ],
)
def test_msk_to_utc_errors(date_str, time_str, tz_name):
    with pytest.raises(ValueError):
        msk_to_utc(date_str, time_str, tz_name)


@pytest.mark.parametrize(
    ("request_utc_iso", "expected_cycle_iso"),
    [
        ("2026-04-22T15:00:00+00:00", "2026-04-22T06:00:00+00:00"),
        ("2026-04-22T18:00:00+00:00", "2026-04-22T12:00:00+00:00"),
        ("2026-04-22T23:59:00+00:00", "2026-04-22T12:00:00+00:00"),
        ("2026-04-23T00:00:00+00:00", "2026-04-22T18:00:00+00:00"),
        ("2026-04-22T06:00:00+00:00", "2026-04-22T00:00:00+00:00"),
        ("2026-04-22T05:59:00+00:00", "2026-04-21T18:00:00+00:00"),
        ("2026-04-22T12:00:00+00:00", "2026-04-22T06:00:00+00:00"),
    ],
)
def test_resolve_gfs_cycle_cases(request_utc_iso, expected_cycle_iso):
    request = datetime.fromisoformat(request_utc_iso)
    assert resolve_gfs_cycle(request).isoformat() == expected_cycle_iso


def test_resolve_gfs_cycle_naive_error():
    with pytest.raises(ValueError):
        resolve_gfs_cycle(datetime(2026, 4, 22, 15, 0))


def test_resolve_gfs_cycle_non_utc_normalized():
    request_msk = datetime(2026, 4, 22, 18, 0, tzinfo=ZoneInfo("Europe/Moscow"))
    # 18:00 MSK = 15:00 UTC -> effective 09:00 UTC -> cycle 06:00 UTC
    assert resolve_gfs_cycle(request_msk).isoformat() == "2026-04-22T06:00:00+00:00"


@pytest.mark.parametrize(
    ("request_utc_iso", "expected_date_iso"),
    [
        ("2026-04-22T15:00:00+00:00", "2026-04-21"),
        ("2026-04-23T00:00:00+00:00", "2026-04-22"),
        ("2026-04-23T11:59:00+00:00", "2026-04-22"),
        ("2026-04-22T23:59:00+00:00", "2026-04-21"),
        ("2026-04-22T12:00:00+00:00", "2026-04-21"),
        ("2026-04-23T00:00:01+00:00", "2026-04-22"),
    ],
)
def test_resolve_cmems_layer_cases(request_utc_iso, expected_date_iso):
    request = datetime.fromisoformat(request_utc_iso)
    assert resolve_cmems_layer(request).isoformat() == expected_date_iso


def test_resolve_cmems_layer_naive_error():
    with pytest.raises(ValueError):
        resolve_cmems_layer(datetime(2026, 4, 22, 15, 0))


def test_parse_args_minimal_valid():
    ns = parse_args(["--date", "2026-04-22", "--time", "18:00"])
    assert ns.date == "2026-04-22"
    assert ns.time == "18:00"
    assert ns.tz == "MSK"
    assert ns.timeout_minutes == 360
    assert ns.polling_minutes == 10
    assert ns.dry_run is False


def test_parse_args_dry_run_utc():
    ns = parse_args(["--date", "2026-04-22", "--time", "18:00", "--tz", "UTC", "--dry-run"])
    assert ns.dry_run is True
    assert ns.tz == "UTC"


def test_parse_args_invalid_tz():
    with pytest.raises(SystemExit):
        parse_args(["--date", "2026-04-22", "--time", "18:00", "--tz", "PST"])


def test_parse_args_invalid_timeout():
    with pytest.raises(SystemExit):
        parse_args(["--date", "2026-04-22", "--time", "18:00", "--timeout-minutes", "5"])


def test_main_dry_run_ok(capsys):
    rc = main(["--date", "2026-04-22", "--time", "18:00", "--dry-run"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "UTC" in captured.out or "UTC" in captured.err
    assert "2026-04-22T15:00:00+00:00" in captured.out or "2026-04-22T15:00:00+00:00" in captured.err
    assert "gfs_cycle:" in captured.out
    assert "cmems_layer:" in captured.out


def test_main_dry_run_invalid_time():
    rc = main(["--date", "2026-04-22", "--time", "25:00", "--dry-run"])
    assert rc == 2
