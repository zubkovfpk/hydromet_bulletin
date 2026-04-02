"""
collect_meteo_data.py
Конвертация MATLAB collect_meteo_data.m → Python

Читает NetCDF-файлы метеопрогноза GFS из папки results/<YYYYMMDD>/,
применяет маску акватории Каспийского моря из шейп-файла,
агрегирует данные по суточным интервалам.
"""

import os
from datetime import date
from pathlib import Path

import numpy as np
import netCDF4 as nc
import geopandas as gpd
from shapely.geometry import Point


def _build_mask(lon_grid: np.ndarray, lat_grid: np.ndarray,
                shapefile_path: str) -> np.ndarray:
    """
    Строит булеву маску акватории по шейп-файлу.
    True = точка находится внутри полигона (акватория).
    """
    gdf = gpd.read_file(shapefile_path)
    union = gdf.unary_union  # объединяем все геометрии в одну

    mask = np.zeros(lon_grid.shape, dtype=bool)
    rows, cols = lon_grid.shape
    for i in range(rows):
        for j in range(cols):
            mask[i, j] = union.contains(Point(lon_grid[i, j], lat_grid[i, j]))
    return mask


def collect_meteo_data(
    base_dir: str = ".",
    results_subdir: str = "Meteo_Parser_2026/results",
    shapefile: str = "Kasp_Sea.shp",
    run_date: str | None = None,
) -> dict:
    """
    Загружает метеоданные GFS и возвращает словарь с массивами.

    Parameters
    ----------
    base_dir        : str  — корневая папка проекта
    results_subdir  : str  — путь к папке results относительно base_dir
    shapefile       : str  — имя shp-файла с контуром акватории
    run_date        : str | None — дата запуска 'YYYYMMDD'; если None — сегодня

    Returns
    -------
    dict с ключами: Temp, Rain, Freeze_Rain, Ice_Pell, Snow,
                    Wind_Gust, U_wind, V_wind, Vis
    Каждое значение — np.ndarray формы (nx, ny, n_days),
    где n_days=5 для большинства, n_days=10 для Temp.
    NaN за пределами акватории.
    """
    if run_date is None:
        run_date = date.today().strftime("%Y%m%d")

    data_dir = Path(base_dir) / results_subdir / run_date

    # Получаем отсортированный список подпапок (каждая = один шаг прогноза)
    subdirs = sorted([d for d in data_dir.iterdir() if d.is_dir()])

    accum: dict[str, list] = {
        "Temp": [], "Rain": [], "Freeze_Rain": [], "Ice_Pell": [],
        "Snow": [], "Wind_Gust": [], "U_wind": [], "V_wind": [], "Vis": []
    }

    lat_arr = lon_arr = None

    for subdir in subdirs:
        nc_files = list(subdir.glob("*.nc"))
        if not nc_files:
            continue
        nc_path = nc_files[0]

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

    # Стекаем в трёхмерные массивы (nx, ny, n_steps)
    stacked: dict[str, np.ndarray] = {k: np.stack(v, axis=2) for k, v in accum.items()}

    # Сетка координат (транспонируем как в MATLAB meshgrid + transpose)
    Lon_raw, Lat_raw = np.meshgrid(lon_arr, lat_arr)
    Lon = Lon_raw.T
    Lat = Lat_raw.T

    # Маска акватории
    shp_path = Path(base_dir) / shapefile
    mask = _build_mask(Lon, Lat, str(shp_path))  # (nx, ny)

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
