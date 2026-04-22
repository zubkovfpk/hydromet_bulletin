import pytest

from forecast_main import main, msk_to_utc, parse_args


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


def test_main_dry_run_invalid_time():
    rc = main(["--date", "2026-04-22", "--time", "25:00", "--dry-run"])
    assert rc == 2
