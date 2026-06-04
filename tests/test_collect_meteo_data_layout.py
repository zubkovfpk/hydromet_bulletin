import pytest

from utils.collect_meteo_data import _discover_gfs_nc_files, _resolve_gfs_data_dir, collect_meteo_data


def test_collect_meteo_data_uses_new_layout_by_default(tmp_path):
    run_date = "20260415"
    cycle = "00z"
    new_dir = tmp_path / "data" / "storage" / "gfs" / run_date / cycle
    new_dir.mkdir(parents=True)
    marker = new_dir / "gfs.t00z.pgrb2.0p25.f006.nc"
    marker.write_text("x", encoding="utf-8")

    resolved = _resolve_gfs_data_dir(
        base_dir=str(tmp_path),
        run_date=run_date,
        cycle=cycle,
        gfs_storage_subdir="data/storage/gfs",
        legacy_results_subdir="Meteo_Parser_2026/results",
    )
    files = _discover_gfs_nc_files(resolved)

    assert resolved == new_dir
    assert files == [marker]


def test_collect_meteo_data_gfs_data_dir_override(tmp_path):
    with pytest.raises(FileNotFoundError, match="custom_dir"):
        collect_meteo_data(
            gfs_data_dir=str(tmp_path / "custom_dir"),
            run_date="20260514",
            cycle="12z",
        )
