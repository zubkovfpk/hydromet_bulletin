# AUTO-GENERATED SKELETON — review before use.
"""CMEMS downloader skeleton for ingestion layer."""

from __future__ import annotations

import configparser
import logging
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

_EXPLICIT_CMEMS_RUN_PARAMS_MSG = (
    "explicit run_hour and first_forecast_dt are required until DT-14-Z (scheduled ingestion); "
    "pass keyword arguments run_hour='00'|'12' and first_forecast_dt='YYYYMMDDHH' (UTC)."
)


def build_cmems_wave_regex(
    run_date: str,
    run_hour: str,
    first_forecast_dt: str,
    forecast_days: int = 5,
) -> str:
    """
    Return regex matching exactly ``2 * forecast_days`` CMEMS wave files for this run.

    Args:
        run_date: YYYYMMDD — model run date (UTC).
        run_hour: "00" or "12" — model run hour (UTC).
        first_forecast_dt: YYYYMMDDHH — nominal forecast_dt hour of the first file in window.
            Must be a valid 12h-aligned timestamp (hour in {"00", "12"}).
        forecast_days: forecast depth in days (default 5 → 10 files × 12h each).

    Returns:
        Regex string matching absolute paths to exactly ``2 * forecast_days`` files.

    Contract:
        Output filenames: ``mfwamglocep_<FORECAST_DT>_R<run_date>_<run_hour>H.nc``.
        FORECAST_DT list: first_forecast_dt, +12h, +24h, ..., +(2*forecast_days - 1)*12h.

    Raises:
        ValueError: if ``run_hour`` not in {"00", "12"}, or ``first_forecast_dt`` hour not in
            {"00", "12"}, or ``forecast_days`` <= 0.
    """
    if run_hour not in {"00", "12"}:
        raise ValueError(f"run_hour must be '00' or '12', got {run_hour!r}")
    if forecast_days <= 0:
        raise ValueError(f"forecast_days must be positive, got {forecast_days}")
    if len(first_forecast_dt) < 2 or first_forecast_dt[-2:] not in {"00", "12"}:
        raise ValueError(
            f"first_forecast_dt must end with hour 00 or 12 (UTC), got {first_forecast_dt!r}"
        )

    fdt = datetime.strptime(first_forecast_dt, "%Y%m%d%H")
    ts_list: list[str] = []
    for i in range(2 * forecast_days):
        ts_list.append((fdt + timedelta(hours=12 * i)).strftime("%Y%m%d%H"))
    assert len(ts_list) == 2 * forecast_days
    alt = "|".join(ts_list)
    return rf".*/mfwamglocep_({alt})_R{run_date}_{run_hour}H\.nc$"


def resolve_cmems_forecast_hours(
    cfg: configparser.ConfigParser,
    logger: logging.Logger | None = None,
) -> int:
    """
    Resolve CMEMS forecast horizon in hours.

    Compat-window beta:
    1) prefer [CMEMS_FORECAST] forecast_hours
    2) fallback to forecast_days * 24 with deprecation warning
    3) fallback to default 120h with warning
    """
    log = logger or logging.getLogger(__name__)

    if cfg.has_option("CMEMS_FORECAST", "forecast_hours"):
        return cfg.getint("CMEMS_FORECAST", "forecast_hours")

    if cfg.has_option("CMEMS_FORECAST", "forecast_days"):
        days = cfg.getint("CMEMS_FORECAST", "forecast_days")
        hours = int(days) * 24
        log.warning(
            "[CMEMS_FORECAST] forecast_days is deprecated; use forecast_hours. "
            "Value derived as %dh.",
            hours,
        )
        return hours

    log.warning(
        "[CMEMS_FORECAST] neither forecast_hours nor forecast_days set; using default 120h."
    )
    return 120


class CMEMSDownloader:
    """Wrapper over CMEMS fetch flow described in project docs.

    Expected config sections:
    - [CMEMS_SOURCES]
    - [CMEMS_FORECAST]
    """

    def __init__(self, cfg: configparser.ConfigParser, logger: logging.Logger | None = None) -> None:
        self.cfg = cfg
        self.logger = logger or logging.getLogger(__name__)

        if not self.cfg.has_section("CMEMS_SOURCES"):
            raise KeyError("Missing [CMEMS_SOURCES] section in config")

        self.cmems_base_url = self.cfg.get("CMEMS_SOURCES", "cmems_base_url", fallback="")
        self.cmems_dataset = self.cfg.get("CMEMS_SOURCES", "cmems_dataset_id", fallback="")
        self.cmems_dynamic_path_mask = self.cfg.get("CMEMS_SOURCES", "cmems_dynamic_path_mask", fallback="/{yyyy}/{mm}/")
        self.cmems_product_path = self.cfg.get("CMEMS_SOURCES", "cmems_product_path", fallback="")

        self.auth_method = self.cfg.get("CMEMS_SOURCES", "cmems_auth_method", fallback="token")
        self.username = self.cfg.get("CMEMS_SOURCES", "cmems_username", fallback="")
        self.password = self.cfg.get("CMEMS_SOURCES", "cmems_password", fallback="")
        self.token = self.cfg.get("CMEMS_SOURCES", "cmems_token", fallback="")
        self.timeout_seconds = self.cfg.getint("DOWNLOAD", "download_timeout_seconds", fallback=600)
        self.max_retries = self.cfg.getint("DOWNLOAD", "download_retry_count", fallback=3)
        self.retry_delay_seconds = self.cfg.getint("DOWNLOAD", "download_retry_delay_seconds", fallback=30)
        self.forecast_hours = resolve_cmems_forecast_hours(self.cfg, self.logger)
        self.download_mode = self.cfg.get(
            "CMEMS_SOURCES",
            "cmems_download_mode",
            fallback="auto",
        ).strip().lower()
        if self.download_mode not in {"auto", "get", "subset"}:
            self.logger.warning(
                "CMEMS: invalid cmems_download_mode=%r, fallback to 'auto'",
                self.download_mode,
            )
            self.download_mode = "auto"
        self.enable_subset_fallback = self.cfg.getboolean(
            "CMEMS_SOURCES",
            "cmems_enable_subset_fallback",
            fallback=True,
        )
        self.work_dir    = Path(self.cfg.get("CMEMS_STORAGE", "CMEMS_WORK_DIR",   fallback=self.cfg.get("STORAGE", "work_dir",    fallback="data/work/cmems")))
        self.storage_dir = Path(self.cfg.get("CMEMS_STORAGE", "CMEMS_OUTPUT_DIR", fallback=self.cfg.get("STORAGE", "storage_dir", fallback="data/storage/cmems")))
        self.replace_existing = self.cfg.getboolean("DOWNLOAD", "replace_same_name_files", fallback=True)
        self.file_patterns_raw = self.cfg.get("CMEMS_FORECAST", "file_name_patterns", fallback="*.nc")
        self.leftlon = self.cfg.getfloat("BoundingBox", "leftlon", fallback=46.0)
        self.rightlon = self.cfg.getfloat("BoundingBox", "rightlon", fallback=55.0)
        self.toplat = self.cfg.getfloat("BoundingBox", "toplat", fallback=48.0)
        self.bottomlat = self.cfg.getfloat("BoundingBox", "bottomlat", fallback=42.0)

    def _ensure_login(self, copernicusmarine):
        """Ensure CMEMS credentials are available for toolbox calls."""
        import os

        env_user = os.environ.get("COPERNICUSMARINE_SERVICE_USERNAME")
        env_pass = os.environ.get("COPERNICUSMARINE_SERVICE_PASSWORD")
        username = env_user or self.username or None
        password = env_pass or self.password or None

        try:
            if self.username and self.password and not (env_user and env_pass):
                credentials_path = Path.home() / ".copernicusmarine" / ".copernicusmarine-credentials"
                if not credentials_path.exists():
                    # Keep existing credentials file if present, avoid interactive overwrite.
                    self._run_with_timeout(
                        lambda: copernicusmarine.login(
                            username=self.username,
                            password=self.password,
                            force_overwrite=False,
                        )
                    )
                else:
                    self.logger.info("CMEMS: using existing credentials file")
            return username, password
        except FuturesTimeoutError:
            self.logger.error(
                "CMEMS: copernicusmarine.login timed out after %ss",
                self.timeout_seconds,
            )
            return None, None
        except Exception:
            self.logger.exception("CMEMS: copernicusmarine.login failed")
            return None, None

    def _run_with_timeout(self, fn: Callable[[], None]) -> None:
        """Execute toolbox call with hard timeout control."""
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(fn)
            future.result(timeout=self.timeout_seconds)

    def _is_s3_retry_error(self, exc: Exception) -> bool:
        """Return True for known CloudFerro/S3 read-timeout patterns."""
        markers = (
            "RetriesExceededError",
            "Max Retries Exceeded",
            "s3.waw3-1.cloudferro.com",
            "Read timeout on endpoint URL",
            "botocore",
        )
        current = exc
        seen: set[int] = set()
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            message = str(current)
            if any(marker in message for marker in markers):
                return True
            current = current.__cause__ or current.__context__
        return False

    def _run_subset_call(self, copernicusmarine, date: str, username, password, start_datetime, end_datetime) -> None:
        """Fallback download via subset API (HTTP path, no direct S3 object pulls)."""
        copernicusmarine.subset(
            dataset_id=self.cmems_dataset,
            minimum_longitude=self.leftlon,
            maximum_longitude=self.rightlon,
            minimum_latitude=self.bottomlat,
            maximum_latitude=self.toplat,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            output_directory=self.storage_dir,
            output_filename=f"cmems_subset_{date}.nc",
            username=username,
            password=password,
            overwrite_output_data=self.replace_existing,
            disable_progress_bar=True,
        )

    def _run_primary_download(
        self,
        copernicusmarine,
        date: str,
        username,
        password,
        start_datetime,
        end_datetime,
        *,
        run_hour: str,
        first_forecast_dt: str,
    ) -> str:
        """Run primary strategy selected by cmems_download_mode."""
        if self.download_mode == "subset":
            self._run_with_timeout(
                lambda: self._run_subset_call(
                    copernicusmarine=copernicusmarine,
                    date=date,
                    username=username,
                    password=password,
                    start_datetime=start_datetime,
                    end_datetime=end_datetime,
                )
            )
            self.logger.info("CMEMS: subset() completed successfully")
            return "subset"

        def _run_get_call() -> None:
            if self.forecast_hours % 24 != 0:
                raise ValueError(
                    f"CMEMS forecast_hours={self.forecast_hours} is not divisible by 24; "
                    "cannot build per-day regex window."
                )
            forecast_days = self.forecast_hours // 24
            regex = build_cmems_wave_regex(
                date,
                run_hour,
                first_forecast_dt,
                forecast_days=forecast_days,
            )
            copernicusmarine.get(
                dataset_id=self.cmems_dataset,
                output_directory=self.storage_dir,
                username=username,
                password=password,
                overwrite=self.replace_existing,
                regex=regex,
                disable_progress_bar=True,
            )

        self._run_with_timeout(_run_get_call)
        self.logger.info("CMEMS: copernicusmarine.get completed successfully")
        return "get"

    def download(
        self,
        date: str,
        *,
        run_hour: str | None = None,
        first_forecast_dt: str | None = None,
    ) -> bool:
        """Download CMEMS inputs for provided date via Copernicus Marine Toolbox.

        Uses ``copernicusmarine.login()`` when username/password are set in config
        and env vars ``COPERNICUSMARINE_SERVICE_*`` are not already set; otherwise
        ``copernicusmarine.get()`` resolves credentials from env or stored files.

        Temporal window for the run day is derived from ``date`` (UTC) and logged;
        file selection uses ``get(..., regex=...)`` because the ``get`` API has no
        ``start_datetime`` / ``end_datetime`` parameters.

        Args:
            date: Run date in YYYYMMDD format (model run date ``R<date>`` in filenames).
            run_hour: ``"00"`` or ``"12"`` — model run hour (UTC); required.
            first_forecast_dt: ``YYYYMMDDHH`` — first forecast slot in the window; required.

        Returns:
            bool: True if ``copernicusmarine.get`` completes without raising.

        Raises:
            ValueError: if ``run_hour`` or ``first_forecast_dt`` is omitted (until DT-14-Z).
        """
        from datetime import datetime, timedelta, timezone

        if run_hour is None or first_forecast_dt is None:
            raise ValueError(_EXPLICIT_CMEMS_RUN_PARAMS_MSG)

        try:
            import copernicusmarine
        except ImportError:
            self.logger.exception("CMEMS: copernicusmarine package is not installed")
            return False

        self.logger.info(
            "CMEMS download: start  date=%s run_hour=%s first_forecast_dt=%s",
            date,
            run_hour,
            first_forecast_dt,
        )

        try:
            day = datetime.strptime(date, "%Y%m%d").replace(tzinfo=timezone.utc)
            start_datetime = day
            end_datetime = day + timedelta(hours=max(1, self.forecast_hours))
        except ValueError:
            self.logger.exception("CMEMS: invalid date (expected YYYYMMDD): %s", date)
            return False

        self.logger.info(
            "CMEMS: window start_datetime=%s end_datetime=%s (UTC)",
            start_datetime.isoformat(),
            end_datetime.isoformat(),
        )

        if not str(self.cmems_dataset).strip():
            self.logger.error("CMEMS: cmems_dataset_id is empty")
            return False

        try:
            self.storage_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            self.logger.exception("CMEMS: cannot create storage_dir %s", self.storage_dir)
            return False

        username, password = self._ensure_login(copernicusmarine)
        if (self.username and self.password) and (username is None and password is None):
            return False

        for attempt in range(1, self.max_retries + 1):
            try:
                self.logger.info(
                    "CMEMS: download attempt %d/%d (mode=%s, timeout=%ss)",
                    attempt,
                    self.max_retries,
                    self.download_mode,
                    self.timeout_seconds,
                )
                self._run_primary_download(
                    copernicusmarine=copernicusmarine,
                    date=date,
                    username=username,
                    password=password,
                    start_datetime=start_datetime,
                    end_datetime=end_datetime,
                    run_hour=run_hour,
                    first_forecast_dt=first_forecast_dt,
                )
                return True
            except FuturesTimeoutError:
                self.logger.error(
                    "CMEMS: attempt %d/%d timed out after %ss",
                    attempt,
                    self.max_retries,
                    self.timeout_seconds,
                )
            except Exception as exc:
                self.logger.exception(
                    "CMEMS: attempt %d/%d failed due to exception",
                    attempt,
                    self.max_retries,
                )
                can_fallback = (
                    self.download_mode in {"auto", "get"}
                    and self.enable_subset_fallback
                    and self._is_s3_retry_error(exc)
                )
                if can_fallback:
                    self.logger.warning(
                        "CMEMS: detected S3 retry/read-timeout; trying subset() fallback "
                        "for attempt %d/%d",
                        attempt,
                        self.max_retries,
                    )
                    try:
                        self._run_with_timeout(
                            lambda: self._run_subset_call(
                                copernicusmarine=copernicusmarine,
                                date=date,
                                username=username,
                                password=password,
                                start_datetime=start_datetime,
                                end_datetime=end_datetime,
                            )
                        )
                        self.logger.info("CMEMS: subset() fallback completed successfully")
                        return True
                    except FuturesTimeoutError:
                        self.logger.error(
                            "CMEMS: subset fallback attempt %d/%d timed out after %ss",
                            attempt,
                            self.max_retries,
                            self.timeout_seconds,
                        )
                    except Exception:
                        self.logger.exception(
                            "CMEMS: subset fallback attempt %d/%d failed due to exception",
                            attempt,
                            self.max_retries,
                        )

            if attempt < self.max_retries:
                sleep_seconds = self.retry_delay_seconds * (2 ** (attempt - 1))
                self.logger.info(
                    "CMEMS: waiting %ss before next retry",
                    sleep_seconds,
                )
                time.sleep(sleep_seconds)

        self.logger.error("CMEMS: all retry attempts exhausted")
        return False
