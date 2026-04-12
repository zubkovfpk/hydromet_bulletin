# AUTO-GENERATED SKELETON — review before use.
"""GFS downloader skeleton for ingestion layer."""

from __future__ import annotations

import configparser
import logging
import time
from pathlib import Path

import requests


class GFSDownloader:
    """Wrapper over GFS fetch flow described in project docs.

    Expected config sections:
    - [GFS_SOURCES]
    - [GFS_DOWNLOAD]
    - [GFS_FORECAST]
    """

    def __init__(self, cfg: configparser.ConfigParser, logger: logging.Logger | None = None) -> None:
        self.cfg = cfg
        self.logger = logger or logging.getLogger(__name__)

        for section in ("GFS_SOURCES", "GFS_DOWNLOAD", "GFS_FORECAST"):
            if not self.cfg.has_section(section):
                raise KeyError(f"Missing [{section}] section in config")

        self.base_url = self.cfg.get("GFS_SOURCES", "GFS_BASE_URL", fallback="")
        self.model_path_template = self.cfg.get("GFS_SOURCES", "GFS_MODEL_PATH_TEMPLATE", fallback="")
        self.cycles = self.cfg.get("GFS_SOURCES", "GFS_CYCLES", fallback="00z,06z,12z,18z")

        self.frequency_per_day = self.cfg.getint("GFS_DOWNLOAD", "GFS_DOWNLOAD_FREQUENCY_PER_DAY", fallback=2)
        self.timeout_seconds = self.cfg.getint("GFS_DOWNLOAD", "GFS_TIMEOUT_SECONDS", fallback=600)
        self.max_retries = self.cfg.getint("GFS_DOWNLOAD", "GFS_MAX_RETRIES", fallback=3)
        self.retry_delay_seconds = self.cfg.getint("GFS_DOWNLOAD", "GFS_HTTP_RETRY_DELAY_SECONDS", fallback=30)

        self.forecast_hours_start = self.cfg.getint("GFS_FORECAST", "GFS_FORECAST_HOURS_START", fallback=0)
        self.forecast_hours_end = self.cfg.getint("GFS_FORECAST", "GFS_FORECAST_HOURS_END", fallback=72)
        self.forecast_hours_step = self.cfg.getint("GFS_FORECAST", "GFS_FORECAST_HOURS_STEP", fallback=1)
        self.variables = self.cfg.get("GFS_FORECAST", "GFS_VARIABLES", fallback="")
        self.levels = self.cfg.get("GFS_FORECAST", "GFS_LEVELS", fallback="")
        self.work_dir = Path(
            self.cfg.get("GFS_STORAGE", "GFS_WORK_DIR", fallback="data/work/gfs")
        )
        self.enable_conversion_to_netcdf = (
            self.cfg.getboolean("GFS_VALIDATION", "GFS_ENABLE_CONVERSION_TO_NETCDF", fallback=False)
            if self.cfg.has_section("GFS_VALIDATION")
            else False
        )

    def download(self, date: str, cycle: str) -> bool:
        """Download GFS inputs for date/cycle.

        Planned steps (from docs/Collecting_GFS_weather_data.md):
        1) Determine target date and model cycle (00z/06z/12z/18z).
        2) Build NOMADS filter URL from template and runtime params.
        3) Send HTTP request with selected variables/levels/forecast hours.
        4) Save downloaded artifacts into working directory.
        5) Ensure required formats (GRIB2/NetCDF) are present.
        6) Verify forecast-hours completeness and retry when needed.

        Args:
            date: Run date in YYYYMMDD format.
            cycle: Model cycle, e.g. 00z/06z/12z/18z.

        Returns:
            bool: True when ingestion succeeds, False otherwise.
        """
        self.logger.info("GFS download requested for date=%s cycle=%s", date, cycle)
        session = requests.Session()
        session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; hydromet-bulletin/1.0)"})

        try:
            cycle_num = cycle.lower().replace("z", "").strip()
            model_path = self.model_path_template.replace("{yyyymmdd}", date).replace("{cycle}", cycle_num)
            self.logger.info("GFS NOMADS base URL: %s  dir=/%s", self.base_url, model_path.lstrip("/"))
        except Exception:
            self.logger.exception("GFS: failed to build model path")
            return False

        # Step 2 - Build target forecast files list.
        try:
            hours = list(
                range(
                    self.forecast_hours_start,
                    self.forecast_hours_end + 1,
                    self.forecast_hours_step,
                )
            )
            forecast_files = [f"gfs.t{cycle_num}z.pgrb2.0p25.f{hour:03d}" for hour in hours]
        except Exception:
            self.logger.exception("GFS: failed to build forecast file list")
            return False

        # Step 3 - Download with retry.
        try:
            self.work_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            self.logger.exception("GFS: failed to create work dir: %s", self.work_dir)
            return False

        downloaded_files: dict[int, Path] = {}
        for hour, file_name in zip(hours, forecast_files):
            target_path = self.work_dir / file_name
            file_url = f"{self.base_url.rstrip('/')}/{model_path.strip('/')}/{file_name}"

            success = False
            for attempt in range(1, self.max_retries + 1):
                try:
                    with session.get(
                        file_url,
                        timeout=self.timeout_seconds,
                        stream=True,
                    ) as response:
                        response.raise_for_status()
                        with target_path.open("wb") as file_handle:
                            for chunk in response.iter_content(chunk_size=1024 * 1024):
                                if chunk:
                                    file_handle.write(chunk)
                    success = True
                    downloaded_files[hour] = target_path
                    self.logger.info("GFS download OK: %s", file_name)
                    break
                except Exception:
                    self.logger.exception(
                        "GFS download failed: %s (attempt %d/%d)",
                        file_name,
                        attempt,
                        self.max_retries,
                    )
                    if attempt < self.max_retries:
                        time.sleep(self.retry_delay_seconds)

            if not success:
                self.logger.error("GFS retries exhausted: %s", file_name)

        # Step 4 - Format checks.
        non_empty_hours: set[int] = set()
        for hour, file_path in downloaded_files.items():
            try:
                if file_path.stat().st_size > 0:
                    non_empty_hours.add(hour)
                    self.logger.info("GFS validation OK: %s", file_path.name)
                else:
                    self.logger.error("GFS validation failed (empty file): %s", file_path.name)
            except Exception:
                self.logger.exception("GFS validation failed: %s", file_path.name)

        if self.enable_conversion_to_netcdf:
            self.logger.info(
                "GFS conversion flag is enabled: NetCDF conversion is planned (stub only)."
            )

        # Step 5 - Completeness check.
        expected_hours = set(hours)
        missing_hours = sorted(expected_hours - non_empty_hours)
        if missing_hours:
            self.logger.warning(
                "GFS forecast incomplete: expected=%d, ready=%d, missing_hours=%s",
                len(expected_hours),
                len(non_empty_hours),
                ",".join(f"{h:03d}" for h in missing_hours),
            )
            return False

        self.logger.info(
            "GFS download complete: expected=%d downloaded=%d non_empty=%d",
            len(expected_hours),
            len(downloaded_files),
            len(non_empty_hours),
        )
        return len(non_empty_hours) == len(expected_hours)
