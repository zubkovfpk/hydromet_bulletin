# AUTO-GENERATED SKELETON — review before use.
"""CMEMS downloader skeleton for ingestion layer."""

from __future__ import annotations

import configparser
import fnmatch
import logging
import time
from pathlib import Path

import requests


class CMEMSDownloader:
    """Wrapper over CMEMS fetch flow described in project docs.

    Expected config sections:
    - [SOURCES]
    - [AUTH]
    """

    def __init__(self, cfg: configparser.ConfigParser, logger: logging.Logger | None = None) -> None:
        self.cfg = cfg
        self.logger = logger or logging.getLogger(__name__)

        if not self.cfg.has_section("SOURCES"):
            raise KeyError("Missing [SOURCES] section in config")
        if not self.cfg.has_section("AUTH"):
            raise KeyError("Missing [AUTH] section in config")

        self.cmems_base_url = self.cfg.get("SOURCES", "base_url", fallback="")
        self.cmems_dataset = self.cfg.get("SOURCES", "dataset_id", fallback="")
        self.cmems_dynamic_path_mask = self.cfg.get("SOURCES", "dynamic_path_mask", fallback="/{yyyy}/{mm}/")

        self.auth_method = self.cfg.get("AUTH", "cmems_auth_method", fallback="token")
        self.username = self.cfg.get("AUTH", "cmems_username", fallback="")
        self.password = self.cfg.get("AUTH", "cmems_password", fallback="")
        self.token = self.cfg.get("AUTH", "cmems_token", fallback="")
        self.timeout_seconds = self.cfg.getint("DOWNLOAD", "download_timeout_seconds", fallback=600)
        self.max_retries = self.cfg.getint("DOWNLOAD", "download_retry_count", fallback=3)
        self.retry_delay_seconds = self.cfg.getint("DOWNLOAD", "download_retry_delay_seconds", fallback=30)
        self.storage_dir = Path(self.cfg.get("STORAGE", "storage_dir", fallback="data/storage"))
        self.replace_existing = self.cfg.getboolean("DOWNLOAD", "replace_same_name_files", fallback=True)
        self.file_patterns_raw = self.cfg.get("FORECAST", "file_name_patterns", fallback="*.nc")

    def download(self, date: str) -> bool:
        """Download CMEMS inputs for provided date.

        Steps (from docs/Collecting_ocean_disturbance_data.md):
        1) Authorize at CMEMS portal via token or password.
        2) Resolve dynamic /yyyy/mm catalog path for run date.
        3) Fetch file listing from catalog and filter by configured patterns.
        4) Download each file with retry; save to work_dir.
        5) Validate each file: non-empty + optional NetCDF variable check.
        6) Move valid files to storage_dir; log summary.

        Args:
            date: Run date in YYYYMMDD format.

        Returns:
            bool: True when all selected files are downloaded and valid.
        """
        self.logger.info("CMEMS download: start  date=%s", date)
        session = requests.Session()

        base_url = self.cmems_base_url
        dynamic_mask = self.cmems_dynamic_path_mask
        file_patterns = [p.strip() for p in self.file_patterns_raw.split(",") if p.strip()] or ["*.nc"]
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        # Step 1 — Authorization.
        try:
            if self.auth_method == "token":
                if not self.token:
                    self.logger.error("CMEMS auth failed: empty token")
                    return False
                session.headers.update({"Authorization": f"Bearer {self.token}"})
            elif self.auth_method == "password":
                if not self.username or not self.password:
                    self.logger.error("CMEMS auth failed: empty username/password")
                    return False
                session.auth = (self.username, self.password)
            else:
                self.logger.error("CMEMS auth failed: unsupported auth method '%s'", self.auth_method)
                return False
        except Exception:
            self.logger.exception("CMEMS auth failed")
            return False

        # Step 2 — Dynamic path.
        try:
            yyyy = date[:4]
            mm = date[4:6]
            dynamic_path = dynamic_mask.replace("{yyyy}", yyyy).replace("{mm}", mm)
            catalog_url = f"{base_url.rstrip('/')}/{dynamic_path.lstrip('/')}"
            self.logger.info("CMEMS catalog URL: %s", catalog_url)
        except Exception:
            self.logger.exception("CMEMS: failed to build dynamic catalog path")
            return False

        # Step 3 — Select files.
        try:
            response = session.get(catalog_url, timeout=self.timeout_seconds)
            response.raise_for_status()
            response_text = response.text
        except Exception:
            self.logger.exception("CMEMS: failed to fetch file listing")
            return False

        selected_files: list[str] = []
        seen: set[str] = set()
        for raw_line in response_text.splitlines():
            line = raw_line.strip().strip('"').strip("'")
            if not line or "/" in line:
                continue
            if any(fnmatch.fnmatch(line, pattern) for pattern in file_patterns):
                if line not in seen:
                    selected_files.append(line)
                    seen.add(line)

        if not selected_files:
            self.logger.error("CMEMS: no files matched patterns %s", file_patterns)
            return False

        # Step 4 — Download with retry.
        downloaded_files: list[Path] = []
        for file_name in selected_files:
            target_path = self.storage_dir / file_name
            if target_path.exists() and not self.replace_existing:
                self.logger.info("CMEMS: keeping existing file %s", file_name)
                downloaded_files.append(target_path)
                continue

            file_url = f"{catalog_url.rstrip('/')}/{file_name}"
            success = False
            for attempt in range(1, self.max_retries + 1):
                try:
                    with session.get(file_url, timeout=self.timeout_seconds, stream=True) as file_response:
                        file_response.raise_for_status()
                        with target_path.open("wb") as file_handle:
                            for chunk in file_response.iter_content(chunk_size=1024 * 1024):
                                if chunk:
                                    file_handle.write(chunk)
                    success = True
                    downloaded_files.append(target_path)
                    break
                except Exception:
                    self.logger.exception(
                        "CMEMS: download failed for %s (attempt %d/%d)",
                        file_name,
                        attempt,
                        self.max_retries,
                    )
                    if attempt < self.max_retries:
                        time.sleep(self.retry_delay_seconds)

            if not success:
                self.logger.error("CMEMS: retries exhausted for %s", file_name)

        # Step 5 — Validation.
        valid_count = 0
        for downloaded in downloaded_files:
            try:
                if downloaded.stat().st_size <= 0:
                    self.logger.error("CMEMS validation failed: empty file %s", downloaded.name)
                    continue

                if downloaded.suffix.lower() == ".nc":
                    try:
                        import netCDF4  # type: ignore

                        with netCDF4.Dataset(str(downloaded), "r"):
                            pass
                    except ImportError:
                        self.logger.warning(
                            "CMEMS validation: netCDF4 unavailable, skip structure check for %s",
                            downloaded.name,
                        )
                    except Exception:
                        self.logger.exception("CMEMS validation failed: NetCDF open error for %s", downloaded.name)
                        continue

                valid_count += 1
                self.logger.info("CMEMS validation OK: %s", downloaded.name)
            except Exception:
                self.logger.exception("CMEMS validation failed: unexpected error for %s", downloaded.name)

        # Step 6 — Finalization.
        downloaded_count = len(downloaded_files)
        selected_count = len(selected_files)
        self.logger.info(
            "CMEMS summary: selected=%d downloaded=%d valid=%d",
            selected_count,
            downloaded_count,
            valid_count,
        )
        return selected_count > 0 and downloaded_count == selected_count and valid_count == selected_count
