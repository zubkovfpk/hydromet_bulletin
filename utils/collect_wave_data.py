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


def _hours_to_date(hours: float) -> datetime:
    return CMEMS_EPOCH + timedelta(hours=float(hours))


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

    Resolution order (DT-11-1):

    1. **Flat layout** — ``{cmems_root}/{run_date}/*.nc`` (documented new layout).
    2. **Nested layout** — ``{cmems_root}/**/mfwamglocep_{run_date}*.nc`` (Copernicus
       toolbox often writes under product/year/month subfolders).
    3. **Legacy** — ``{base_dir}/{legacy_waves_dir}/*.nc``.

    Returns ``(files, tried_descriptions)`` for logging and error diagnostics.
    """
    base = Path(base_dir)
    cmems_root = base / cmems_storage_subdir
    tried: list[str] = []

    flat_dir = cmems_root / run_date
    tried.append(f"flat dated dir: {flat_dir}")
    if flat_dir.is_dir():
        direct = sorted(flat_dir.glob("*.nc"))
        if direct:
            return direct, tried

    nested_pattern = f"mfwamglocep_{run_date}*.nc"
    tried.append(f"nested glob under {cmems_root}: **/{nested_pattern}")
    nested = sorted(cmems_root.glob(f"**/{nested_pattern}"))
    if nested:
        return nested, tried

    legacy_dir = base / legacy_waves_dir
    tried.append(f"legacy waves dir: {legacy_dir}")
    if legacy_dir.is_dir():
        legacy_files = sorted(legacy_dir.glob("*.nc"))
        if legacy_files:
            return legacy_files, tried

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
    Wave       : np.ndarray (nx, ny, 5) — средняя высота волн по суткам
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

    # Глобальный буфер: 4320×2041×40 (как в оригинале)
    # Размер определим по первому файлу
    with nc.Dataset(nc_files[0]) as ds0:
        lon_full = ds0.variables["longitude"][:].data
        lat_full = ds0.variables["latitude"][:].data
        nx_full = len(lon_full)
        ny_full = len(lat_full)

    H_Wave = np.zeros((nx_full, ny_full, 40))
    start_date = end_date = None
    i, j = 3, 6  # индексы слоёв (0-based: 3:7 = шаги 4-7)

    for idx, nc_file in enumerate(nc_files):
        with nc.Dataset(nc_file) as ds:
            h_wave = ds.variables["VHM0_WW"][:]  # (time, lat, lon) → транспонируем
            h_wave = np.transpose(h_wave.data, (2, 1, 0))  # → (lon, lat, time)
            time_arr = ds.variables["time"][:].data

            if idx == 0:
                H_Wave[:, :, 0:3] = h_wave[:, :, 1:4]
                start_date = _hours_to_date(time_arr[0])
            elif idx == len(nc_files) - 1:
                H_Wave[:, :, 39] = h_wave[:, :, 0]
                end_date = _hours_to_date(time_arr[0])
            else:
                end_idx = min(i + 4, 40)
                take = end_idx - i
                H_Wave[:, :, i:end_idx] = h_wave[:, :, :take]
                i += 4
                j += 4

    # Обрезка по области Каспия
    lon_mask = (lon_full >= lon_bounds[0]) & (lon_full <= lon_bounds[1])
    lat_mask = (lat_full >= lat_bounds[0]) & (lat_full <= lat_bounds[1])

    Hwave = H_Wave[np.ix_(lon_mask, lat_mask, np.arange(40))]
    lon_crop = lon_full[lon_mask]
    lat_crop = lat_full[lat_mask]

    Lon_raw, Lat_raw = np.meshgrid(lon_crop, lat_crop)
    Lon = Lon_raw.T
    Lat = Lat_raw.T

    # Маска акватории
    mask = _build_mask(Lon, Lat, str(shp_path))

    # Агрегация: 8 шагов × 3ч = 24ч → 5 суток
    Wave = np.full((*Hwave.shape[:2], 5), np.nan)
    for d in range(5):
        s = d * 8
        e = s + 8
        Wave[:, :, d] = np.mean(Hwave[:, :, s:e], axis=2)

    # Применяем маску
    Wave[~np.broadcast_to(mask[:, :, np.newaxis], Wave.shape)] = np.nan

    return Wave, start_date, end_date
