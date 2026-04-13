# AUTO-GENERATED SKELETON — review before use.
"""CMEMS downloader skeleton for ingestion layer."""

from __future__ import annotations

import configparser
import logging
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
        import os
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

        env_user = os.environ.get("COPERNICUSMARINE_SERVICE_USERNAME")
        env_pass = os.environ.get("COPERNICUSMARINE_SERVICE_PASSWORD")

        try:
            if self.username and self.password and not (env_user and env_pass):
                credentials_path = Path.home() / ".copernicusmarine" / ".copernicusmarine-credentials"
                if not credentials_path.exists():
                    # Toolbox API: force_overwrite=False keeps existing credentials file (no interactive overwrite).
                    copernicusmarine.login(
                        username=self.username,
                        password=self.password,
                        force_overwrite=False,
                    )
                else:
                    self.logger.info("CMEMS: using existing credentials file")
        except Exception:
            self.logger.exception("CMEMS: copernicusmarine.login failed")
            return False

        username = env_user or self.username or None
        password = env_pass or self.password or None

        try:
            copernicusmarine.get(
                dataset_id=self.cmems_dataset,
                output_directory=self.storage_dir,
                username=username,
                password=password,
                overwrite=self.replace_existing,
                filter=f"*{date}*",
                disable_progress_bar=True,
            )
            return True
        except Exception:
            self.logger.exception("CMEMS: copernicusmarine.get failed")
            return False
