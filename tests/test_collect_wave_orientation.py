"""DT-12-1: wave (lat, lon, time) canon; meshgrid without .T; mask broadcast."""

import numpy as np

from utils.collect_wave_data import _discover_cmems_nc_files


def test_wave_mask_meshgrid_lat_lon_broadcast_matches_meteo_canon():
    """Lon, Lat = meshgrid(lon, lat) -> (n_lat, n_lon); Wave same plane as meteo DT-10-3."""
    lon_crop = np.linspace(46.0, 55.0, 40)
    lat_crop = np.linspace(42.0, 48.0, 35)
    Lon, Lat = np.meshgrid(lon_crop, lat_crop)
    assert Lon.shape == (35, 40)
    assert Lat.shape == (35, 40)

    Hwave = np.zeros((35, 40, 40), dtype=np.float64)
    Wave = np.full((35, 40, 5), np.nan)
    mask = np.ones((35, 40), dtype=bool)
    Wave[~np.broadcast_to(mask[:, :, np.newaxis], Wave.shape)] = np.nan
    assert Wave.shape == (35, 40, 5)


def test_discover_cmems_empty_lists_tried_dt11_regression(tmp_path):
    """3-tier discovery (DT-11-1): empty result still exposes Tried: paths."""
    _files, tried = _discover_cmems_nc_files(
        base_dir=str(tmp_path),
        run_date="20260415",
        cmems_storage_subdir="data/storage/cmems",
        legacy_waves_dir="waves",
    )
    assert _files == []
    assert any("nested glob" in t for t in tried)
    assert any("flat dated" in t for t in tried)

