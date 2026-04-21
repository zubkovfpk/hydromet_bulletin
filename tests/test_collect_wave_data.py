from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import netCDF4 as nc
import numpy as np
import pytest

import utils.collect_wave_data as wave_mod
from utils.collect_wave_data import _discover_cmems_nc_files, collect_wave_data
from utils.validate_outputs import validate_wave_output


def _write_wave_file(
    path: Path,
    *,
    start_time_hours_since_1950: float,
    ny: int = 4,
    nx: int = 4,
    fill_positions: set[tuple[int, int, int]] | None = None,
    wrong_time_len: int | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    t_len = wrong_time_len if wrong_time_len is not None else 4
    with nc.Dataset(path, "w", format="NETCDF4") as ds:
        ds.createDimension("time", t_len)
        ds.createDimension("latitude", ny)
        ds.createDimension("longitude", nx)

        t = ds.createVariable("time", "f8", ("time",))
        t[:] = np.array([start_time_hours_since_1950 + 3 * i for i in range(t_len)], dtype=float)

        lat = ds.createVariable("latitude", "f4", ("latitude",))
        lon = ds.createVariable("longitude", "f4", ("longitude",))
        lat[:] = np.linspace(42.0, 45.0, ny)
        lon[:] = np.linspace(46.0, 49.0, nx)

        v = ds.createVariable("VHM0_WW", "f4", ("time", "latitude", "longitude"), fill_value=-32767.0)
        v.missing_value = -32767.0
        data = np.full((t_len, ny, nx), 1.5, dtype=np.float32)
        if fill_positions:
            for it, iy, ix in fill_positions:
                if 0 <= it < t_len and 0 <= iy < ny and 0 <= ix < nx:
                    data[it, iy, ix] = -32767.0
        v[:] = data


def _patch_wave_mask(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    shp = tmp_path / "dummy.shp"
    shp.write_text("dummy", encoding="utf-8")
    monkeypatch.setattr(wave_mod, "_resolve_shapefile_path", lambda _p: shp)
    monkeypatch.setattr(wave_mod, "_build_mask", lambda lon, lat, _s: np.ones(lon.shape, dtype=bool))
    return shp


def test_discover_cmems_nc_files_by_r_label_nested(tmp_path):
    run_date = "20260421"
    nested = tmp_path / "data" / "storage" / "cmems" / "product" / "2026" / "04"
    r_file = nested / "mfwamglocep_2026042112_R20260421_00H.nc"
    prefix_file = nested / "mfwamglocep_20260421_prefix_only.nc"
    _write_wave_file(r_file, start_time_hours_since_1950=667000.0)
    _write_wave_file(prefix_file, start_time_hours_since_1950=667000.0)

    files, _tried = _discover_cmems_nc_files(
        base_dir=str(tmp_path),
        run_date=run_date,
        cmems_storage_subdir="data/storage/cmems",
        legacy_waves_dir="waves",
    )

    assert files == [r_file]


def test_discover_cmems_nc_files_ignores_prefix_without_r_label(tmp_path, caplog):
    run_date = "20260421"
    nested = tmp_path / "data" / "storage" / "cmems" / "product" / "2026" / "04"
    prefix_file = nested / "mfwamglocep_20260421_prefix_only.nc"
    wrong_r_file = nested / "mfwamglocep_2026042112_R20260414_00H.nc"
    _write_wave_file(prefix_file, start_time_hours_since_1950=667000.0)
    _write_wave_file(wrong_r_file, start_time_hours_since_1950=667012.0)

    with caplog.at_level("WARNING"):
        files, _tried = _discover_cmems_nc_files(
            base_dir=str(tmp_path),
            run_date=run_date,
            cmems_storage_subdir="data/storage/cmems",
            legacy_waves_dir="waves",
        )
    assert files == []
    assert "deprecated prefix-based discovery" not in caplog.text


def test_collect_wave_data_full_10_files_no_zero_layers(tmp_path, monkeypatch):
    run_date = "20260421"
    base_hours = 667000.0
    nested = tmp_path / "data" / "storage" / "cmems" / "product" / "2026" / "04"
    for i in range(10):
        ts = (datetime(2026, 4, 21, 12) + timedelta(hours=12 * i)).strftime("%Y%m%d%H")
        fp = nested / f"mfwamglocep_{ts}_R{run_date}_00H.nc"
        _write_wave_file(fp, start_time_hours_since_1950=base_hours + i * 12)

    _patch_wave_mask(monkeypatch, tmp_path)
    wave, start_date, end_date = collect_wave_data(
        base_dir=str(tmp_path),
        shapefile_dir=str(tmp_path),
        run_date=run_date,
        cmems_storage_subdir="data/storage/cmems",
    )

    assert wave.shape == (4, 4, 5)
    assert start_date < end_date
    for i in range(wave.shape[2]):
        layer = wave[:, :, i]
        non_nan = layer[~np.isnan(layer)]
        assert non_nan.size > 0
        assert np.any(non_nan != 0.0)


def test_collect_wave_data_fill_value_decoded_to_nan(tmp_path, monkeypatch):
    run_date = "20260421"
    nested = tmp_path / "data" / "storage" / "cmems" / "product" / "2026" / "04"
    for i in range(10):
        ts = (datetime(2026, 4, 21, 12) + timedelta(hours=12 * i)).strftime("%Y%m%d%H")
        fp = nested / f"mfwamglocep_{ts}_R{run_date}_00H.nc"
        fill_positions = {(0, 0, 0)} if i == 0 else None
        _write_wave_file(fp, start_time_hours_since_1950=667000.0 + i * 12, fill_positions=fill_positions)

    _patch_wave_mask(monkeypatch, tmp_path)
    wave, _start_date, _end_date = collect_wave_data(
        base_dir=str(tmp_path),
        shapefile_dir=str(tmp_path),
        run_date=run_date,
        cmems_storage_subdir="data/storage/cmems",
    )
    assert np.nanmin(wave) > -1000.0


def test_collect_wave_data_partial_set_produces_nan_layers(tmp_path, monkeypatch):
    run_date = "20260421"
    nested = tmp_path / "data" / "storage" / "cmems" / "product" / "2026" / "04"
    for i in range(2):
        ts = (datetime(2026, 4, 21, 12) + timedelta(hours=12 * i)).strftime("%Y%m%d%H")
        fp = nested / f"mfwamglocep_{ts}_R{run_date}_00H.nc"
        _write_wave_file(fp, start_time_hours_since_1950=667000.0 + i * 12)

    _patch_wave_mask(monkeypatch, tmp_path)
    wave, start_date, end_date = collect_wave_data(
        base_dir=str(tmp_path),
        shapefile_dir=str(tmp_path),
        run_date=run_date,
        cmems_storage_subdir="data/storage/cmems",
    )
    assert np.isnan(wave[:, :, 2]).all()
    report = validate_wave_output(wave, start_date, end_date, strict=True, forecast_hours=120, tol_hours=3)
    assert any(issue["code"] == "all_nan_layer" for issue in report["errors"])


def test_collect_wave_data_wrong_timesteps_per_file_raises(tmp_path, monkeypatch):
    run_date = "20260421"
    nested = tmp_path / "data" / "storage" / "cmems" / "product" / "2026" / "04"
    fp = nested / f"mfwamglocep_2026042112_R{run_date}_00H.nc"
    _write_wave_file(fp, start_time_hours_since_1950=667000.0, wrong_time_len=3)

    _patch_wave_mask(monkeypatch, tmp_path)
    with pytest.raises(AssertionError, match="Unexpected time length"):
        collect_wave_data(
            base_dir=str(tmp_path),
            shapefile_dir=str(tmp_path),
            run_date=run_date,
            cmems_storage_subdir="data/storage/cmems",
        )
