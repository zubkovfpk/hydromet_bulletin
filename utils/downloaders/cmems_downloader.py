# AUTO-GENERATED SKELETON — review before use.
"""CMEMS downloader skeleton for ingestion layer."""

from __future__ import annotations

import configparser
import logging
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from pathlib import Path


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
        self.storage_dir = Path(self.cfg.get("STORAGE", "storage_dir", fallback="data/storage"))
        self.replace_existing = self.cfg.getboolean("DOWNLOAD", "replace_same_name_files", fallback=True)
        self.file_patterns_raw = self.cfg.get("CMEMS_FORECAST", "file_name_patterns", fallback="*.nc")

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
                    copernicusmarine.login(
                        username=self.username,
                        password=self.password,
                        force_overwrite=False,
                    )
                else:
                    self.logger.info("CMEMS: using existing credentials file")
            return username, password
        except Exception:
            self.logger.exception("CMEMS: copernicusmarine.login failed")
            return None, None

    def download(self, date: str) -> bool:
        """Download CMEMS inputs for provided date via Copernicus Marine Toolbox.

        Uses ``copernicusmarine.login()`` when username/password are set in config
        and env vars ``COPERNICUSMARINE_SERVICE_*`` are not already set; otherwise
        ``copernicusmarine.get()`` resolves credentials from env or stored files.

        Temporal window for the run day is derived from ``date`` (UTC) and logged;
        file selection uses ``get(..., filter=...)`` because the ``get`` API has no
        ``start_datetime`` / ``end_datetime`` parameters.

        Args:
            date: Run date in YYYYMMDD format.

        Returns:
            bool: True if ``copernicusmarine.get`` completes without raising.
        """
        from datetime import datetime, timedelta, timezone

        try:
            import copernicusmarine
        except ImportError:
            self.logger.exception("CMEMS: copernicusmarine package is not installed")
            return False

        self.logger.info("CMEMS download: start  date=%s", date)

        try:
            day = datetime.strptime(date, "%Y%m%d").replace(tzinfo=timezone.utc)
            start_datetime = day
            end_datetime = day + timedelta(days=1)
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

        def _run_get_call() -> None:
            copernicusmarine.get(
                dataset_id=self.cmems_dataset,
                output_directory=self.storage_dir,
                username=username,
                password=password,
                overwrite=self.replace_existing,
                filter=f"*{date}*",
                disable_progress_bar=True,
            )

        for attempt in range(1, self.max_retries + 1):
            try:
                self.logger.info(
                    "CMEMS: download attempt %d/%d (timeout=%ss)",
                    attempt,
                    self.max_retries,
                    self.timeout_seconds,
                )
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(_run_get_call)
                    future.result(timeout=self.timeout_seconds)
                self.logger.info("CMEMS: copernicusmarine.get completed successfully")
                return True
            except FuturesTimeoutError:
                self.logger.error(
                    "CMEMS: attempt %d/%d timed out after %ss",
                    attempt,
                    self.max_retries,
                    self.timeout_seconds,
                )
            except Exception:
                self.logger.exception(
                    "CMEMS: attempt %d/%d failed due to exception",
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
