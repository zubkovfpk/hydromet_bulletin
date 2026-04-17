"""GFS downloader — NOMADS filter_gfs_0p25_1hr via requests."""

from __future__ import annotations

import configparser
import logging
import time
from pathlib import Path

import requests


class GFSDownloader:
    """Загрузка GFS-прогноза через NOMADS filter_gfs_0p25_1hr.pl.

    Читает секции конфига:
    - [GFS_SOURCES]
    - [GFS_DOWNLOAD]
    - [GFS_FORECAST]
    - [GFS_STORAGE]
    - [GFS_VALIDATION]
    """

    _CFGRIB_TO_PROCESSING_NAMES = {
        "t": "Temperature_surface",
        "crain": "Categorical_Rain_surface",
        "cfrzr": "Categorical_Freezing_Rain_surface",
        "cicep": "Categorical_Ice_Pellets_surface",
        "csnow": "Categorical_Snow_surface",
        "gust": "Wind_speed_gust_surface",
        "u10": "u-component_of_wind_height_above_ground",
        "v10": "v-component_of_wind_height_above_ground",
        "vis": "Visibility_surface",
    }

    def __init__(
        self,
        cfg: configparser.ConfigParser,
        logger: logging.Logger | None = None,
    ) -> None:
        self.cfg = cfg
        self.logger = logger or logging.getLogger(__name__)

        for section in ("GFS_SOURCES", "GFS_DOWNLOAD", "GFS_FORECAST", "GFS_STORAGE"):
            if not self.cfg.has_section(section):
                raise KeyError(f"Missing [{section}] section in config")

        # [GFS_SOURCES]
        self.main_url            = self.cfg.get("GFS_SOURCES", "GFS_MAIN_URL")
        self.model_path_template = self.cfg.get("GFS_SOURCES", "GFS_MODEL_PATH_TEMPLATE")
        self.cycles              = self.cfg.get("GFS_SOURCES", "GFS_CYCLES", fallback="00z,06z,12z,18z")

        # [GFS_DOWNLOAD]
        self.timeout_seconds     = self.cfg.getint("GFS_DOWNLOAD", "GFS_TIMEOUT_SECONDS",          fallback=600)
        self.max_retries         = self.cfg.getint("GFS_DOWNLOAD", "GFS_MAX_RETRIES",              fallback=3)
        self.retry_delay_seconds = self.cfg.getint("GFS_DOWNLOAD", "GFS_HTTP_RETRY_DELAY_SECONDS", fallback=30)

        # [GFS_FORECAST]
        self.hours_start     = self.cfg.getint("GFS_FORECAST", "GFS_FORECAST_HOURS_START", fallback=6)
        self.hours_end       = self.cfg.getint("GFS_FORECAST", "GFS_FORECAST_HOURS_END",   fallback=123)
        self.hours_step      = self.cfg.getint("GFS_FORECAST", "GFS_FORECAST_HOURS_STEP",  fallback=3)
        self.variables_str   = self.cfg.get("GFS_FORECAST", "GFS_VARIABLES", fallback="")
        self.levels_str      = self.cfg.get("GFS_FORECAST", "GFS_LEVELS",    fallback="")

        # [GFS_STORAGE]
        self.work_dir    = Path(self.cfg.get("GFS_STORAGE", "GFS_WORK_DIR",   fallback="data/work/gfs"))
        self.storage_dir = Path(self.cfg.get("GFS_STORAGE", "GFS_OUTPUT_DIR", fallback="data/storage/gfs"))

        # [GFS_VALIDATION]
        self.check_completeness = (
            self.cfg.getboolean("GFS_VALIDATION", "GFS_CHECK_FORECAST_COMPLETENESS", fallback=True)
            if self.cfg.has_section("GFS_VALIDATION") else True
        )
        self.min_expected_files = (
            self.cfg.getint("GFS_VALIDATION", "GFS_MIN_EXPECTED_FILES", fallback=40)
            if self.cfg.has_section("GFS_VALIDATION") else 40
        )
        self.enable_netcdf_conversion = (
            self.cfg.getboolean("GFS_VALIDATION", "GFS_ENABLE_CONVERSION_TO_NETCDF", fallback=True)
            if self.cfg.has_section("GFS_VALIDATION") else True
        )

    # ------------------------------------------------------------------
    # Вспомогательные методы
    # ------------------------------------------------------------------

    def _build_query(self, date: str, cycle_num: str, fxx: int) -> dict:
        """Формирует параметры запроса для NOMADS filter URL.

        Пример результата:
        {
            'file': 'gfs.t00z.pgrb2.0p25.f006',
            'dir': '/gfs.20260413/00/atmos',
            'var_CFRZR': 'on',
            ...
            'lev_surface': 'on',
            ...
        }
        """
        params = {
            "file": f"gfs.t{cycle_num}z.pgrb2.0p25.f{fxx:03d}",
            "dir":  f"/gfs.{date}/{cycle_num}/atmos",
        }

        # GFS_VARIABLES = "var_CFRZR=on&var_CRAIN=on&..." → {'var_CFRZR': 'on', ...}
        for token in self.variables_str.split("&"):
            token = token.strip()
            if "=" in token:
                key, val = token.split("=", 1)
                params[key.strip()] = val.strip()

        # GFS_LEVELS = "lev_10_m_above_ground=on&lev_surface=on" → {'lev_surface': 'on', ...}
        for token in self.levels_str.split("&"):
            token = token.strip()
            if "=" in token:
                key, val = token.split("=", 1)
                params[key.strip()] = val.strip()

        return params

    def _netcdf_output_path(self, grib_path: Path) -> Path:
        """Build sidecar .nc path next to GRIB2 file."""
        return Path(f"{grib_path}.nc")

    def _normalize_cfgrib_dataset(self, dataset):
        """Normalize cfgrib dataset to names expected by processing layer."""
        rename_dims: dict[str, str] = {}
        if "latitude" in dataset.dims:
            rename_dims["latitude"] = "lat"
        if "longitude" in dataset.dims:
            rename_dims["longitude"] = "lon"
        if rename_dims:
            dataset = dataset.rename(rename_dims)

        rename_vars = {
            key: val
            for key, val in self._CFGRIB_TO_PROCESSING_NAMES.items()
            if key in dataset.variables
        }
        if rename_vars:
            dataset = dataset.rename(rename_vars)
        return dataset

    def _convert_grib_to_netcdf(self, grib_path: Path, nc_path: Path) -> bool:
        """Convert one GFS GRIB2 file to NetCDF for processing layer."""
        try:
            import cfgrib  # type: ignore
            import xarray as xr  # type: ignore
        except ImportError:
            self.logger.exception(
                "GFS NetCDF conversion dependency missing for %s. "
                "Install cfgrib+xarray+eccodes.",
                grib_path.name,
            )
            return False

        try:
            datasets = cfgrib.open_datasets(
                str(grib_path),
                backend_kwargs={"indexpath": ""},
            )
            if not datasets:
                self.logger.error("GFS NetCDF conversion returned no datasets: %s", grib_path.name)
                return False

            normalized = [self._normalize_cfgrib_dataset(ds) for ds in datasets]
            merged = xr.merge(normalized, compat="override", join="outer")
            merged.to_netcdf(nc_path)
            self.logger.info("GFS NetCDF created: %s", nc_path.name)
            return nc_path.exists() and nc_path.stat().st_size > 0
        except Exception:
            self.logger.exception("GFS NetCDF conversion failed: %s", grib_path.name)
            return False

    def _ensure_netcdf_for_grib(self, grib_path: Path) -> bool:
        """
        Ensure sidecar NetCDF exists for downloaded GRIB2 file.

        When conversion is disabled, keeps previous GRIB2-only behavior.
        """
        if not self.enable_netcdf_conversion:
            return True

        nc_path = self._netcdf_output_path(grib_path)
        if nc_path.exists() and nc_path.stat().st_size > 0:
            self.logger.info("GFS NetCDF skip (exists): %s", nc_path.name)
            return True
        return self._convert_grib_to_netcdf(grib_path, nc_path)

    def convert_existing(self, date: str, cycle: str) -> int:
        """Convert already-downloaded GRIB2 files to NetCDF.

        Используется когда GRIB2 уже скачаны, но .nc ещё не созданы.
        Возвращает количество успешно конвертированных файлов.
        """
        if not self.enable_netcdf_conversion:
            self.logger.info("GFS NetCDF conversion disabled, skipping.")
            return 0

        cycle_num = cycle.lower().replace("z", "").strip()
        out_dir = self.storage_dir / date / f"{cycle_num}z"

        if not out_dir.exists():
            self.logger.warning("GFS storage dir not found: %s", out_dir)
            return 0

        grib_files = sorted(out_dir.glob("gfs.t*.pgrb2.0p25.f*"))
        if not grib_files:
            self.logger.warning("No GRIB2 files found in: %s", out_dir)
            return 0

        self.logger.info(
            "GFS converting %d GRIB2 files for %s/%s",
            len(grib_files), date, cycle
        )
        converted = 0
        for grib_path in grib_files:
            if self._ensure_netcdf_for_grib(grib_path):
                converted += 1

        self.logger.info(
            "GFS conversion complete: %d/%d files", converted, len(grib_files)
        )
        return converted

    # ------------------------------------------------------------------
    # Основной метод
    # ------------------------------------------------------------------

    def download(self, date: str, cycle: str) -> bool:
        """Скачать GFS-прогноз для date/cycle через NOMADS filter.

        Args:
            date:  Дата инициализации в формате YYYYMMDD.
            cycle: Цикл модели: '00z', '06z', '12z', '18z'.

        Returns:
            True — все шаги скачаны успешно, False — иначе.
        """
        self.logger.info("GFS download started: date=%s cycle=%s", date, cycle)

        cycle_num = cycle.lower().replace("z", "").strip()
        hours = list(range(self.hours_start, self.hours_end + 1, self.hours_step))
        out_dir = self.storage_dir / date / f"{cycle_num}z"
        out_dir.mkdir(parents=True, exist_ok=True)

        session = requests.Session()
        session.headers.update({"User-Agent": "hydromet-bulletin/1.0"})

        success_count = 0

        for fxx in hours:
            params      = self._build_query(date, cycle_num, fxx)
            file_name   = params["file"]
            target_path = out_dir / file_name
            grib_ready = False

            if target_path.exists() and target_path.stat().st_size > 0:
                self.logger.info("GFS skip (exists): %s", file_name)
                grib_ready = True

            if not grib_ready:
                for attempt in range(1, self.max_retries + 1):
                    try:
                        with session.get(
                            self.main_url,
                            params=params,
                            timeout=self.timeout_seconds,
                            stream=True,
                        ) as response:
                            response.raise_for_status()
                            with target_path.open("wb") as fh:
                                for chunk in response.iter_content(chunk_size=1024 * 1024):
                                    if chunk:
                                        fh.write(chunk)

                        if target_path.stat().st_size > 0:
                            self.logger.info("GFS OK: %s", file_name)
                            grib_ready = True
                        else:
                            self.logger.error("GFS empty file: %s", file_name)

                        break

                    except Exception:
                        self.logger.exception(
                            "GFS failed: %s attempt=%d/%d", file_name, attempt, self.max_retries
                        )
                        if attempt < self.max_retries:
                            time.sleep(self.retry_delay_seconds)

            if not grib_ready:
                self.logger.error("GFS retries exhausted: %s", file_name)
                continue

            if not self._ensure_netcdf_for_grib(target_path):
                self.logger.error("GFS NetCDF missing after conversion: %s", target_path.name)
                continue

            success_count += 1

        for idx_file in out_dir.glob("*.idx"):
            idx_file.unlink()

        # Проверка полноты
        if self.check_completeness and success_count < self.min_expected_files:
            self.logger.warning(
                "GFS incomplete: expected>=%d got=%d", self.min_expected_files, success_count
            )
            return False

        self.logger.info(
            "GFS download complete: steps=%d success=%d", len(hours), success_count
        )
        return success_count == len(hours)