import pytest

from utils.collect_meteo_data import (
    _normalize_cycle,
    _discover_gfs_nc_files,
    collect_meteo_data,
    _resolve_shapefile_path as _resolve_meteo_shapefile_path,
    _resolve_gfs_data_dir,
)
from utils.collect_wave_data import (
    _resolve_cmems_wave_dir,
    _resolve_shapefile_path as _resolve_wave_shapefile_path,
    collect_wave_data,
)


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


@pytest.mark.parametrize(
    ("raw_cycle", "expected"),
    [
        ("00z", "00z"),
        ("12", "12z"),
        ("  00Z  ", "00z"),
        ("", "00z"),
        (None, "00z"),
    ],
)
def test_normalize_cycle_supported_values(raw_cycle, expected):
    assert _normalize_cycle(raw_cycle) == expected


@pytest.mark.xfail(reason="Current implementation returns '6z', pending zero-pad normalization to '06z'.")
def test_normalize_cycle_single_digit_zero_padded():
    assert _normalize_cycle("6") == "06z"


def test_collect_meteo_data_raises_file_not_found_for_absent_dirs(tmp_path):
    run_date = "20260415"
    cycle = "00z"
    with pytest.raises(FileNotFoundError) as exc_info:
        collect_meteo_data(
            base_dir=str(tmp_path),
            run_date=run_date,
            cycle=cycle,
            gfs_storage_subdir="data/storage/gfs",
            results_subdir="Meteo_Parser_2026/results",
        )
    msg = str(exc_info.value)
    assert f"run_date={run_date}" in msg
    assert f"cycle={cycle}" in msg
    assert "Checked:" in msg


def test_collect_wave_data_raises_file_not_found_for_absent_dirs(tmp_path):
    run_date = "20260415"
    with pytest.raises(FileNotFoundError) as exc_info:
        collect_wave_data(
            base_dir=str(tmp_path),
            run_date=run_date,
            cmems_storage_subdir="data/storage/cmems",
            waves_dir="waves",
        )
    msg = str(exc_info.value)
    assert f"run_date={run_date}" in msg
    assert "Checked:" in msg


def test_resolve_shapefile_path_uses_structured_dir(tmp_path):
    shapefile_dir = tmp_path / "data" / "shapefiles"
    expected = shapefile_dir / "Kasp_Sea" / "Kasp_Sea.shp"
    assert _resolve_meteo_shapefile_path(str(shapefile_dir)) == expected
    assert _resolve_wave_shapefile_path(str(shapefile_dir)) == expected


def test_collect_meteo_data_raises_file_not_found_for_missing_shapefile(tmp_path):
    run_date = "20260415"
    cycle = "00z"
    gfs_dir = tmp_path / "data" / "storage" / "gfs" / run_date / cycle
    gfs_dir.mkdir(parents=True)
    (gfs_dir / "one.nc").write_text("x", encoding="utf-8")

    shapefile_dir = tmp_path / "data" / "shapefiles"
    shapefile_dir.mkdir(parents=True)

    with pytest.raises(FileNotFoundError) as exc_info:
        collect_meteo_data(
            base_dir=str(tmp_path),
            shapefile_dir=str(shapefile_dir),
            run_date=run_date,
            cycle=cycle,
            gfs_storage_subdir="data/storage/gfs",
            results_subdir="Meteo_Parser_2026/results",
        )
    assert "Shapefile not found:" in str(exc_info.value)


def test_collect_wave_data_raises_file_not_found_for_missing_shapefile(tmp_path):
    run_date = "20260415"
    cmems_dir = tmp_path / "data" / "storage" / "cmems" / run_date
    cmems_dir.mkdir(parents=True)
    (cmems_dir / "one.nc").write_text("x", encoding="utf-8")

    shapefile_dir = tmp_path / "data" / "shapefiles"
    shapefile_dir.mkdir(parents=True)

    with pytest.raises(FileNotFoundError) as exc_info:
        collect_wave_data(
            base_dir=str(tmp_path),
            shapefile_dir=str(shapefile_dir),
            run_date=run_date,
            cmems_storage_subdir="data/storage/cmems",
            waves_dir="waves",
        )
    assert "Shapefile not found:" in str(exc_info.value)
