"""
collect_meteo_data.py
Конвертация MATLAB collect_meteo_data.m → Python

Читает NetCDF-файлы метеопрогноза GFS из папки data/storage/gfs/YYYYMMDD/HHz/ (с fallback на legacy layout),
применяет маску акватории Каспийского моря из шейп-файла,
агрегирует данные по суточным интервалам.
"""

import os
import logging
from datetime import date
from pathlib import Path

import numpy as np
import netCDF4 as nc
import geopandas as gpd
from shapely.geometry import Point

logger = logging.getLogger(__name__)

_LEGACY_WAVES_DIR = "waves"
_LEGACY_GFS_RESULTS_SUBDIR = "Meteo_Parser_2026/results"


def _build_mask(lon_grid: np.ndarray, lat_grid: np.ndarray,
                shapefile_path: str) -> np.ndarray:
    """
    Строит булеву маску акватории по шейп-файлу.
    True = точка находится внутри полигона (акватория).
    """
    shp_path = Path(shapefile_path)
    if not shp_path.exists():
        raise FileNotFoundError(f"Shapefile not found: {shp_path}")

    gdf = gpd.read_file(shapefile_path)
    union = gdf.unary_union  # объединяем все геометрии в одну

    mask = np.zeros(lon_grid.shape, dtype=bool)
    rows, cols = lon_grid.shape
    for i in range(rows):
        for j in range(cols):
            mask[i, j] = union.contains(Point(lon_grid[i, j], lat_grid[i, j]))
    return mask


def _normalize_cycle(cycle: str | None) -> str:
    if not cycle:
        return "00z"
    cycle_norm = cycle.strip().lower()
    return cycle_norm if cycle_norm.endswith("z") else f"{cycle_norm}z"


def _resolve_gfs_data_dir(
    base_dir: str,
    run_date: str,
    cycle: str | None,
    gfs_storage_subdir: str,
    legacy_results_subdir: str,
) -> Path:
    """
    Resolve GFS input directory using new storage layout with legacy fallback.

    New layout: data/storage/gfs/YYYYMMDD/HHz/
    Legacy layout: Meteo_Parser_2026/results/YYYYMMDD/
    """
    cycle_dir = _normalize_cycle(cycle)
    new_layout_dir = Path(base_dir) / gfs_storage_subdir / run_date / cycle_dir
    if new_layout_dir.exists():
        logger.info("GFS data dir resolved: %s", new_layout_dir)
        return new_layout_dir
    legacy_dir = Path(base_dir) / legacy_results_subdir / run_date
    logger.info("GFS data dir resolved: %s", legacy_dir)
    return legacy_dir


def _discover_gfs_nc_files(data_dir: Path) -> list[Path]:
    """
    Collect GFS NetCDF files from both flat and nested layouts.

    - New layout: *.nc files directly in YYYYMMDD/HHz/
    - Legacy layout: one step per subdirectory with *.nc inside
    """
    if not data_dir.exists():
        return []

    direct_nc = sorted(data_dir.glob("*.nc"))
    if direct_nc:
        return direct_nc

    nested_nc: list[Path] = []
    for subdir in sorted([d for d in data_dir.iterdir() if d.is_dir()]):
        nested_nc.extend(sorted(subdir.glob("*.nc")))
    return nested_nc


def _resolve_shapefile_path(shapefile_dir: str) -> Path:
    """
    Resolve shapefile path using structured directory layout:

    data/shapefiles/Kasp_Sea/Kasp_Sea.shp
    """
    return Path(shapefile_dir) / "Kasp_Sea" / "Kasp_Sea.shp"


def has_cmems_for_date(base_dir: str, run_date: str, cmems_storage_subdir: str) -> bool:
    """Return True iff at least one CMEMS .nc exists for run_date."""
    from utils.collect_wave_data import _discover_cmems_nc_files

    files, _ = _discover_cmems_nc_files(
        base_dir=base_dir,
        run_date=run_date,
        cmems_storage_subdir=cmems_storage_subdir,
        legacy_waves_dir=_LEGACY_WAVES_DIR,
    )
    return bool(files)


def has_gfs_for_date(base_dir: str, run_date: str, gfs_storage_subdir: str, gfs_cycle: str) -> bool:
    """Return True iff at least one GFS .nc exists for run_date/cycle."""
    data_dir = _resolve_gfs_data_dir(
        base_dir=base_dir,
        run_date=run_date,
        cycle=gfs_cycle,
        gfs_storage_subdir=gfs_storage_subdir,
        legacy_results_subdir=_LEGACY_GFS_RESULTS_SUBDIR,
    )
    return bool(_discover_gfs_nc_files(data_dir))


def collect_meteo_data(
    base_dir: str = ".",
    shapefile_dir: str | None = None,
    results_subdir: str = _LEGACY_GFS_RESULTS_SUBDIR,
    gfs_storage_subdir: str = "data/storage/gfs",
    run_date: str | None = None,
    cycle: str | None = None,
) -> dict:
    """
    Загружает метеоданные GFS и возвращает словарь с массивами.

    Parameters
    ----------
    base_dir        : str  — корневая папка проекта
    shapefile_dir   : str | None — путь к каталогу shapefiles; если None — %(basedir)s/data/shapefiles
    results_subdir  : str  — legacy путь к папке results относительно base_dir
    gfs_storage_subdir : str — путь к новому GFS storage относительно base_dir
    run_date        : str | None — дата запуска 'YYYYMMDD'; если None — сегодня
    cycle           : str | None — цикл GFS ('00z'/'06z'/'12z'/'18z'), если None — '00z'

    Returns
    -------
    dict с ключами: Temp, Rain, Freeze_Rain, Ice_Pell, Snow,
                    Wind_Gust, U_wind, V_wind, Vis
    Каждое значение — np.ndarray формы (n_lat, n_lon, n_days)
    (широта × долгота × сутки),
    где n_days=5 для большинства, n_days=10 для Temp.
    NaN за пределами акватории.
    """
    if run_date is None:
        run_date = date.today().strftime("%Y%m%d")
    if shapefile_dir is None:
        shapefile_dir = str(Path(base_dir) / "data" / "shapefiles")

    data_dir = _resolve_gfs_data_dir(
        base_dir=base_dir,
        run_date=run_date,
        cycle=cycle,
        gfs_storage_subdir=gfs_storage_subdir,
        legacy_results_subdir=results_subdir,
    )
    nc_files = _discover_gfs_nc_files(data_dir)
    if not nc_files:
        raise FileNotFoundError(
            f"No GFS .nc files found for run_date={run_date}, "
            f"cycle={cycle}. Checked: {data_dir}"
        )

    shp_path = _resolve_shapefile_path(shapefile_dir)
    if not shp_path.exists():
        raise FileNotFoundError(f"Shapefile not found: {shp_path}")

    accum: dict[str, list] = {
        "Temp": [], "Rain": [], "Freeze_Rain": [], "Ice_Pell": [],
        "Snow": [], "Wind_Gust": [], "U_wind": [], "V_wind": [], "Vis": []
    }

    lat_arr = lon_arr = None

    for nc_path in nc_files:
        with nc.Dataset(nc_path) as ds:
            accum["Temp"].append(ds.variables["Temperature_surface"][:].data)
            accum["Rain"].append(ds.variables["Categorical_Rain_surface"][:].data)
            accum["Freeze_Rain"].append(ds.variables["Categorical_Freezing_Rain_surface"][:].data)
            accum["Ice_Pell"].append(ds.variables["Categorical_Ice_Pellets_surface"][:].data)
            accum["Snow"].append(ds.variables["Categorical_Snow_surface"][:].data)
            accum["Wind_Gust"].append(ds.variables["Wind_speed_gust_surface"][:].data)
            accum["U_wind"].append(ds.variables["u-component_of_wind_height_above_ground"][:].data)
            accum["V_wind"].append(ds.variables["v-component_of_wind_height_above_ground"][:].data)
            accum["Vis"].append(ds.variables["Visibility_surface"][:].data)

            if lat_arr is None:
                lat_arr = ds.variables["lat"][:].data.astype(float)
                lon_arr = ds.variables["lon"][:].data.astype(float)

    # Стекаем в трёхмерные массивы (n_lat, n_lon, n_steps) — каноника для processing layer
    stacked: dict[str, np.ndarray] = {k: np.stack(v, axis=2) for k, v in accum.items()}

    # Сетка координат: meshgrid(..., indexing="xy") даёт Lon/Lat формы (len(lat), len(lon)),
    # совпадающей с первыми двумя осям stacked. Транспонирование .T здесь не применяем:
    # в MATLAB-версии column-major индексация меняла порядок осей и ломала согласование с NumPy.
    Lon, Lat = np.meshgrid(lon_arr, lat_arr)

    # Маска акватории
    mask = _build_mask(Lon, Lat, str(shp_path))  # (n_lat, n_lon)
    logger.info(
        "Caspian mask: shape=%s, cells_inside=%d",
        mask.shape,
        int(np.sum(mask)),
    )

    # Агрегация по суткам: шаги по 3ч → 8 шагов на сутки
    # Для большинства переменных: среднее за 8 шагов = 1 сутки (5 суток)
    # Для Temp: среднее за 4 шага = 12ч-интервал (10 интервалов)
    result: dict[str, np.ndarray] = {}

    def daily_mean(arr: np.ndarray, steps_per_day: int, n_days: int) -> np.ndarray:
        out = np.full((*arr.shape[:2], n_days), np.nan)
        for d in range(n_days):
            i = d * steps_per_day
            j = i + steps_per_day
            if j <= arr.shape[2]:
                out[:, :, d] = np.mean(arr[:, :, i:j], axis=2)
        return out

    for key in ["Rain", "Freeze_Rain", "Ice_Pell", "Snow", "Wind_Gust", "U_wind", "V_wind", "Vis"]:
        agg = daily_mean(stacked[key], steps_per_day=8, n_days=5)
        # Применяем маску
        agg[~np.broadcast_to(mask[:, :, np.newaxis], agg.shape)] = np.nan
        result[key] = agg

    # Температура: 4-шаговые периоды (12ч), 10 интервалов
    temp_agg = daily_mean(stacked["Temp"], steps_per_day=4, n_days=10)
    temp_agg = temp_agg - 273.15  # Кельвины → Цельсий
    temp_agg[~np.broadcast_to(mask[:, :, np.newaxis], temp_agg.shape)] = np.nan
    result["Temp"] = temp_agg

    return result
