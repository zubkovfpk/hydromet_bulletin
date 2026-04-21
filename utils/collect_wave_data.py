"""
collect_wave_data.py
Конвертация MATLAB collect_wave_data.m → Python

Читает NetCDF-файлы волнового прогноза CMEMS (mfwamglocep_*.nc),
вырезает область Каспийского моря, агрегирует по суткам.
"""

from __future__ import annotations

import logging
from pathlib import Path
from datetime import datetime, timedelta, date

import numpy as np
import netCDF4 as nc
import geopandas as gpd
from shapely.geometry import Point

logger = logging.getLogger(__name__)


# Epoch CMEMS: часы с 1950-01-01
CMEMS_EPOCH = datetime(1950, 1, 1)
NOMINAL_WAVE_DAYS: int = 5
CMEMS_WAVE_FILES_PER_RUN: int = 10
CMEMS_WAVE_TIMESTEPS_PER_FILE: int = 4
CMEMS_WAVE_TOTAL_TIMESTEPS: int = 40
CMEMS_WAVE_TIMESTEPS_PER_DAY: int = 8
CMEMS_WAVE_VAR_NAME: str = "VHM0_WW"
CMEMS_WAVE_FILL_VALUE: int = -32767
# Нормативные параметры wave-контракта CMEMS для bulletin generation.
# См. docs/project_context.md (CMEMS wave temporal contract, session 14).


def _hours_to_date(hours: float) -> datetime:
    return CMEMS_EPOCH + timedelta(hours=float(hours))


def _derive_time_bounds(time_arrays: list[np.ndarray]) -> tuple[datetime, datetime]:
    """
    Derive global time bounds from all CMEMS files.

    Uses union of all time values (duplicates allowed in source, ignored here).
    """
    if not time_arrays:
        raise ValueError("CMEMS time arrays are empty.")

    all_hours = np.concatenate([np.asarray(arr).ravel() for arr in time_arrays])
    if all_hours.size == 0:
        raise ValueError("CMEMS time arrays contain no values.")

    uniq_hours = np.unique(all_hours)
    return _hours_to_date(float(np.min(uniq_hours))), _hours_to_date(float(np.max(uniq_hours)))


def _build_mask(lon_grid: np.ndarray, lat_grid: np.ndarray,
                shapefile_path: str) -> np.ndarray:
    shp_path = Path(shapefile_path)
    if not shp_path.exists():
        raise FileNotFoundError(f"Shapefile not found: {shp_path}")

    gdf = gpd.read_file(shapefile_path)
    union = gdf.unary_union
    mask = np.zeros(lon_grid.shape, dtype=bool)
    for i in range(lon_grid.shape[0]):
        for j in range(lon_grid.shape[1]):
            mask[i, j] = union.contains(Point(lon_grid[i, j], lat_grid[i, j]))
    return mask


def _resolve_cmems_wave_dir(
    base_dir: str,
    run_date: str,
    cmems_storage_subdir: str,
    legacy_waves_dir: str,
) -> Path:
    """
    Resolve CMEMS directory using new storage layout with legacy fallback.

    New layout: data/storage/cmems/YYYYMMDD/
    Legacy layout: waves/
    """
    new_layout_dir = Path(base_dir) / cmems_storage_subdir / run_date
    if new_layout_dir.exists():
        return new_layout_dir
    return Path(base_dir) / legacy_waves_dir


def _discover_cmems_nc_files(
    base_dir: str,
    run_date: str,
    cmems_storage_subdir: str,
    legacy_waves_dir: str,
) -> tuple[list[Path], list[str]]:
    """
    Locate CMEMS wave NetCDF files for ``run_date`` (YYYYMMDD).

    Resolution order (R-label only; no prefix fallback):

    1. **Flat layout (R-label)** — ``{cmems_root}/{run_date}/*_R{run_date}_*.nc``.
    2. **Nested layout (R-label)** — ``{cmems_root}/**/mfwamglocep_*_R{run_date}_*.nc``.
    3. **Legacy** — ``{base_dir}/{legacy_waves_dir}/*_R{run_date}_*.nc``.
       Files without ``R{run_date}`` attribution are ignored.

    Returns ``(files, tried_descriptions)`` for logging and error diagnostics.
    """
    base = Path(base_dir)
    cmems_root = base / cmems_storage_subdir
    tried: list[str] = []

    flat_dir = cmems_root / run_date
    rlabel_pattern = f"*_R{run_date}_*.nc"
    tried.append(f"flat dated dir (R-label): {flat_dir}/{rlabel_pattern}")
    if flat_dir.is_dir():
        direct_rlabel = sorted(flat_dir.glob(rlabel_pattern))
        if direct_rlabel:
            return direct_rlabel, tried

    nested_rlabel_pattern = f"mfwamglocep_*_R{run_date}_*.nc"
    tried.append(f"nested glob under {cmems_root}: **/{nested_rlabel_pattern}")
    nested_rlabel = sorted(cmems_root.glob(f"**/{nested_rlabel_pattern}"))
    if nested_rlabel:
        return nested_rlabel, tried

    legacy_dir = base / legacy_waves_dir
    tried.append(f"legacy waves dir (R-label): {legacy_dir}/{rlabel_pattern}")
    if legacy_dir.is_dir():
        legacy_rlabel = sorted(legacy_dir.glob(rlabel_pattern))
        if legacy_rlabel:
            return legacy_rlabel, tried

    return [], tried


def _resolve_shapefile_path(shapefile_dir: str) -> Path:
    """
    Resolve shapefile path using structured directory layout:

    data/shapefiles/Kasp_Sea/Kasp_Sea.shp
    """
    return Path(shapefile_dir) / "Kasp_Sea" / "Kasp_Sea.shp"


def collect_wave_data(
    base_dir: str = ".",
    shapefile_dir: str | None = None,
    waves_dir: str = "waves",
    cmems_storage_subdir: str = "data/storage/cmems",
    lon_bounds: tuple = (46, 55),
    lat_bounds: tuple = (42, 48),
    run_date: str | None = None,
) -> tuple[np.ndarray, datetime, datetime]:
    """
    Загружает данные высоты волн VHM0_WW из CMEMS.

    Parameters
    ----------
    base_dir   : str   — корневая папка проекта
    shapefile_dir   : str | None — путь к каталогу shapefiles; если None — %(basedir)s/data/shapefiles
    waves_dir  : str   — legacy подпапка с .nc файлами волн
    cmems_storage_subdir : str — путь к новому CMEMS storage относительно base_dir
    lon_bounds : tuple — (min_lon, max_lon) для обрезки
    lat_bounds : tuple — (min_lat, max_lat) для обрезки
    run_date   : str | None — дата запуска 'YYYYMMDD'; если None — сегодня

    Returns
    -------
    Wave       : np.ndarray (n_lat, n_lon, 5) — средняя высота волн по суткам
                 (каноника processing layer: lat, lon, time — как meteo после DT-10-3)
    start_date : datetime
    end_date   : datetime
    """
    if run_date is None:
        run_date = date.today().strftime("%Y%m%d")
    if shapefile_dir is None:
        shapefile_dir = str(Path(base_dir) / "data" / "shapefiles")

    nc_files, tried_locations = _discover_cmems_nc_files(
        base_dir=base_dir,
        run_date=run_date,
        cmems_storage_subdir=cmems_storage_subdir,
        legacy_waves_dir=waves_dir,
    )
    if not nc_files:
        detail = "\n  - ".join(tried_locations)
        raise FileNotFoundError(
            f"No CMEMS .nc files found for run_date={run_date}. "
            "If CMEMS was never downloaded for this date, ingest data first (not a lookup bug). "
            "If files exist on disk but are not under the flat dated folder, nested discovery "
            "should find mfwamglocep_{date}*.nc under the CMEMS storage root. "
            f"Tried:\n  - {detail}"
        )

    logger.info(
        "CMEMS wave files resolved: count=%d, dir=%s",
        len(nc_files),
        nc_files[0].parent,
    )

    shp_path = _resolve_shapefile_path(shapefile_dir)
    if not shp_path.exists():
        raise FileNotFoundError(f"Shapefile not found: {shp_path}")

    # Глобальный буфер: (n_lat, n_lon, 40) — каноника lat-first, без 3D transpose от NetCDF
    # VHM0_WW в CMEMS: (time, latitude, longitude); заполняем H_Wave[:, :, t_slot]
    with nc.Dataset(nc_files[0]) as ds0:
        lon_full = ds0.variables["longitude"][:].data
        lat_full = ds0.variables["latitude"][:].data
        nx_full = len(lon_full)
        ny_full = len(lat_full)

    H_Wave = np.full((ny_full, nx_full, CMEMS_WAVE_TOTAL_TIMESTEPS), np.nan, dtype=float)
    all_time_arrays: list[np.ndarray] = []

    for idx, nc_file in enumerate(nc_files):
        with nc.Dataset(nc_file) as ds:
            var = ds.variables[CMEMS_WAVE_VAR_NAME]
            hw_raw = var[:]
            if np.ma.isMaskedArray(hw_raw):
                hw = np.ma.filled(hw_raw, np.nan).astype(float)
            else:
                hw = np.asarray(hw_raw, dtype=float)
            fill = getattr(var, "_FillValue", None)
            if fill is None:
                fill = getattr(var, "missing_value", None)
            if fill is not None:
                hw = np.where(hw == float(fill), np.nan, hw)
            else:
                logger.warning(
                    "CMEMS %s: no _FillValue/missing_value attribute in %s, fill decoding skipped",
                    CMEMS_WAVE_VAR_NAME,
                    nc_file,
                )
            time_arr = np.asarray(ds.variables["time"][:].data)
            all_time_arrays.append(time_arr)
            assert hw.shape[0] == CMEMS_WAVE_TIMESTEPS_PER_FILE, (
                f"Unexpected time length in {nc_file}: got {hw.shape[0]}, "
                f"expected {CMEMS_WAVE_TIMESTEPS_PER_FILE}"
            )
            s = idx * CMEMS_WAVE_TIMESTEPS_PER_FILE
            e = min(s + CMEMS_WAVE_TIMESTEPS_PER_FILE, CMEMS_WAVE_TOTAL_TIMESTEPS)
            take = e - s
            if take > 0:
                H_Wave[:, :, s:e] = hw[:take, :, :].transpose(1, 2, 0)

    start_date, end_date = _derive_time_bounds(all_time_arrays)
    logger.info(
        "CMEMS time bounds: files=%d, start=%s, end=%s, delta_days=%d",
        len(nc_files),
        start_date.isoformat(),
        end_date.isoformat(),
        (end_date - start_date).days,
    )

    # Обрезка по области Каспия (ось 0 = lat, ось 1 = lon)
    lon_mask = (lon_full >= lon_bounds[0]) & (lon_full <= lon_bounds[1])
    lat_mask = (lat_full >= lat_bounds[0]) & (lat_full <= lat_bounds[1])

    Hwave = H_Wave[lat_mask, :, :][:, lon_mask, :]
    lon_crop = lon_full[lon_mask]
    lat_crop = lat_full[lat_mask]

    Lon, Lat = np.meshgrid(lon_crop, lat_crop)

    # Маска акватории (n_lat, n_lon) — как в collect_meteo_data после DT-10-3
    mask = _build_mask(Lon, Lat, str(shp_path))

    logger.info(
        "Wave stack: Hwave=%s, mask=%s, inside=%d",
        Hwave.shape,
        mask.shape,
        int(np.sum(mask)),
    )

    # Агрегация: 8 шагов × 3ч = 24ч → 5 суток
    Wave = np.full((*Hwave.shape[:2], NOMINAL_WAVE_DAYS), np.nan)
    for d in range(NOMINAL_WAVE_DAYS):
        s = d * CMEMS_WAVE_TIMESTEPS_PER_DAY
        e = s + CMEMS_WAVE_TIMESTEPS_PER_DAY
        Wave[:, :, d] = np.nanmean(Hwave[:, :, s:e], axis=2)

    # Применяем маску
    Wave[~np.broadcast_to(mask[:, :, np.newaxis], Wave.shape)] = np.nan

    return Wave, start_date, end_date
