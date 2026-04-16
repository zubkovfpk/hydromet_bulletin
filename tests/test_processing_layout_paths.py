from utils.collect_meteo_data import (
    _discover_gfs_nc_files,
    _resolve_gfs_data_dir,
)
from utils.collect_wave_data import _resolve_cmems_wave_dir


def test_resolve_gfs_data_dir_prefers_new_layout(tmp_path):
    run_date = "20260415"
    cycle = "12z"
    new_dir = tmp_path / "data" / "storage" / "gfs" / run_date / cycle
    new_dir.mkdir(parents=True)

    resolved = _resolve_gfs_data_dir(
        base_dir=str(tmp_path),
        run_date=run_date,
        cycle=cycle,
        gfs_storage_subdir="data/storage/gfs",
        legacy_results_subdir="Meteo_Parser_2026/results",
    )

    assert resolved == new_dir


def test_resolve_gfs_data_dir_falls_back_to_legacy(tmp_path):
    run_date = "20260415"
    legacy = tmp_path / "Meteo_Parser_2026" / "results" / run_date
    legacy.mkdir(parents=True)

    resolved = _resolve_gfs_data_dir(
        base_dir=str(tmp_path),
        run_date=run_date,
        cycle="00z",
        gfs_storage_subdir="data/storage/gfs",
        legacy_results_subdir="Meteo_Parser_2026/results",
    )

    assert resolved == legacy


def test_discover_gfs_nc_files_handles_flat_layout(tmp_path):
    data_dir = tmp_path / "data" / "storage" / "gfs" / "20260415" / "00z"
    data_dir.mkdir(parents=True)
    a = data_dir / "gfs.t00z.pgrb2.0p25.f006.nc"
    b = data_dir / "gfs.t00z.pgrb2.0p25.f009.nc"
    a.write_text("x", encoding="utf-8")
    b.write_text("x", encoding="utf-8")

    files = _discover_gfs_nc_files(data_dir)
    assert files == [a, b]


def test_discover_gfs_nc_files_handles_nested_legacy_layout(tmp_path):
    data_dir = tmp_path / "Meteo_Parser_2026" / "results" / "20260415"
    sub1 = data_dir / "step1"
    sub2 = data_dir / "step2"
    sub1.mkdir(parents=True)
    sub2.mkdir(parents=True)
    a = sub1 / "one.nc"
    b = sub2 / "two.nc"
    a.write_text("x", encoding="utf-8")
    b.write_text("x", encoding="utf-8")

    files = _discover_gfs_nc_files(data_dir)
    assert files == [a, b]


def test_resolve_cmems_wave_dir_prefers_dated_storage_dir(tmp_path):
    run_date = "20260415"
    dated = tmp_path / "data" / "storage" / "cmems" / run_date
    dated.mkdir(parents=True)

    resolved = _resolve_cmems_wave_dir(
        base_dir=str(tmp_path),
        run_date=run_date,
        cmems_storage_subdir="data/storage/cmems",
        legacy_waves_dir="waves",
    )
    assert resolved == dated


def test_resolve_cmems_wave_dir_falls_back_to_legacy(tmp_path):
    legacy = tmp_path / "waves"
    legacy.mkdir(parents=True)

    resolved = _resolve_cmems_wave_dir(
        base_dir=str(tmp_path),
        run_date="20260415",
        cmems_storage_subdir="data/storage/cmems",
        legacy_waves_dir="waves",
    )
    assert resolved == legacy
