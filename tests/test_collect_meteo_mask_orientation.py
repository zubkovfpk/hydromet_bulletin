"""DT-10-3: mask grid orientation matches stacked GFS arrays (lat, lon, time)."""

import numpy as np


def test_meshgrid_lon_lat_matches_stack_shape_without_transpose():
    """meshgrid(lon, lat) gives (n_lat, n_lon), same as np.stack(..., axis=2) plane."""
    lon_arr = np.linspace(40.0, 50.0, 1440)
    lat_arr = np.linspace(35.0, 45.0, 721)
    Lon, Lat = np.meshgrid(lon_arr, lat_arr)
    assert Lon.shape == (721, 1440)
    assert Lat.shape == (721, 1440)
    stacked = np.zeros((721, 1440, 40), dtype=np.float64)
    assert Lon.shape == stacked.shape[:2]


def test_broadcast_mask_to_agg_721_1440_ndays():
    """Same pattern as collect_meteo_data: mask (721,1440) with agg (721,1440,5)."""
    mask = np.ones((721, 1440), dtype=bool)
    agg = np.zeros((721, 1440, 5), dtype=np.float64)
    agg[~np.broadcast_to(mask[:, :, np.newaxis], agg.shape)] = np.nan
    assert agg.shape == (721, 1440, 5)
    assert np.isfinite(agg).all()
