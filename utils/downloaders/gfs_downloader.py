"""GFS downloader — NOMADS filter_gfs_0p25_1hr via requests."""

from __future__ import annotations

import configparser
import logging
import time
from pathlib import Path
from urllib.parse import urlencode

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
        self.work_dir = Path(self.cfg.get("GFS_STORAGE", "GFS_WORK_DIR", fallback="data/work/gfs"))

        # [GFS_VALIDATION]
        self.check_completeness = (
            self.cfg.getboolean("GFS_VALIDATION", "GFS_CHECK_FORECAST_COMPLETENESS", fallback=True)
            if self.cfg.has_section("GFS_VALIDATION") else True
        )
        self.min_expected_files = (
            self.cfg.getint("GFS_VALIDATION", "GFS_MIN_EXPECTED_FILES", fallback=40)
            if self.cfg.has_section("GFS_VALIDATION") else 40
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
        self.work_dir.mkdir(parents=True, exist_ok=True)

        session = requests.Session()
        session.headers.update({"User-Agent": "hydromet-bulletin/1.0"})

        success_count = 0

        for fxx in hours:
            params      = self._build_query(date, cycle_num, fxx)
            file_name   = params["file"]
            target_path = self.work_dir / file_name
            downloaded  = False

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
                        downloaded = True
                        success_count += 1
                    else:
                        self.logger.error("GFS empty file: %s", file_name)

                    break

                except Exception:
                    self.logger.exception(
                        "GFS failed: %s attempt=%d/%d", file_name, attempt, self.max_retries
                    )
                    if attempt < self.max_retries:
                        time.sleep(self.retry_delay_seconds)

            if not downloaded:
                self.logger.error("GFS retries exhausted: %s", file_name)

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