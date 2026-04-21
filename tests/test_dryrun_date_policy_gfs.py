from datetime import datetime, timedelta, timezone

import pytest

import forecast_morning


def _today_prev_str() -> tuple[str, str]:
    today = datetime.now(timezone.utc).date()
    return today.strftime("%Y%m%d"), (today - timedelta(days=1)).strftime("%Y%m%d")


def _touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("")


def _make_cmems_marker(tmp_path, run_date: str) -> None:
    _touch(
        tmp_path
        / "data"
        / "storage"
        / "cmems"
        / run_date
        / f"mfwamglocep_{run_date}12_R{run_date}_00H.nc"
    )


def _make_gfs_marker(tmp_path, run_date: str, cycle: str = "00z") -> None:
    _touch(tmp_path / "data" / "storage" / "gfs" / run_date / cycle / "marker.nc")


def test_fallback_to_yesterday_when_gfs_missing_today(tmp_path, caplog):
    today_str, prev_str = _today_prev_str()
    _make_cmems_marker(tmp_path, today_str)
    _make_cmems_marker(tmp_path, prev_str)
    _make_gfs_marker(tmp_path, prev_str)

    with caplog.at_level("WARNING"):
        resolved = forecast_morning._resolve_run_date_for_dry_run(
            explicit_run_date=None,
            base_dir=str(tmp_path),
            cmems_storage_subdir="data/storage/cmems",
            gfs_storage_subdir="data/storage/gfs",
            gfs_cycle="00z",
        )

    assert resolved == prev_str
    assert f"cmems=True, gfs=False" in caplog.text


def test_hard_fail_when_both_days_incomplete(tmp_path):
    today_str, prev_str = _today_prev_str()
    _make_cmems_marker(tmp_path, today_str)

    with pytest.raises(FileNotFoundError) as exc_info:
        forecast_morning._resolve_run_date_for_dry_run(
            explicit_run_date=None,
            base_dir=str(tmp_path),
            cmems_storage_subdir="data/storage/cmems",
            gfs_storage_subdir="data/storage/gfs",
            gfs_cycle="00z",
        )

    message = str(exc_info.value)
    assert f"today={today_str}(cmems=True,gfs=False)" in message
    assert f"today-1={prev_str}(cmems=False,gfs=False)" in message


def test_today_ok_when_cmems_and_gfs_present(tmp_path):
    today_str, _ = _today_prev_str()
    _make_cmems_marker(tmp_path, today_str)
    _make_gfs_marker(tmp_path, today_str)

    resolved = forecast_morning._resolve_run_date_for_dry_run(
        explicit_run_date=None,
        base_dir=str(tmp_path),
        cmems_storage_subdir="data/storage/cmems",
        gfs_storage_subdir="data/storage/gfs",
        gfs_cycle="00z",
    )

    assert resolved == today_str
