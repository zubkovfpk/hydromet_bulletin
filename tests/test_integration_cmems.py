# Integration tests for CMEMSDownloader — require real credentials, make real HTTP requests.
from __future__ import annotations

import configparser
import logging
import os
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / os.environ.get("CMEMS_TEST_CONFIG", "config.example.ini")

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _inject_utils_package_stubs() -> None:
    """Avoid importing utils/__init__.py (pulls numpy/geopandas) when loading downloaders."""
    if "utils" not in sys.modules:
        utils_pkg = types.ModuleType("utils")
        utils_pkg.__path__ = [str(PROJECT_ROOT / "utils")]
        sys.modules["utils"] = utils_pkg
    if "utils.downloaders" not in sys.modules:
        dl_pkg = types.ModuleType("utils.downloaders")
        dl_pkg.__path__ = [str(PROJECT_ROOT / "utils" / "downloaders")]
        sys.modules["utils.downloaders"] = dl_pkg


_inject_utils_package_stubs()

from utils.downloaders.cmems_downloader import CMEMSDownloader  # noqa: E402


def _load_example_config() -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    read = cfg.read(CONFIG_PATH, encoding="utf-8")
    if not read:
        raise FileNotFoundError(f"Cannot read config: {CONFIG_PATH}")
    return cfg


def _has_credentials(cfg: configparser.ConfigParser) -> bool:
    """Return True if usable CMEMS credentials are available."""
    if os.environ.get("COPERNICUSMARINE_SERVICE_USERNAME", "").strip():
        return True
    username = cfg.get("CMEMS_SOURCES", "cmems_username", fallback="").strip()
    password = cfg.get("CMEMS_SOURCES", "cmems_password", fallback="").strip()
    placeholder_values = {"", "CHANGE_ME", "your_username", "your_password"}
    return username not in placeholder_values and password not in placeholder_values


def _make_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(logging.DEBUG)
        logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    return logger


@pytest.mark.integration
class TestCMEMSIntegration(unittest.TestCase):

    def setUp(self) -> None:
        self.cfg = _load_example_config()
        self.logger = _make_logger("test_integration_cmems")
        if not _has_credentials(self.cfg):
            self.skipTest(
                "No CMEMS credentials found: set COPERNICUSMARINE_SERVICE_USERNAME env var "
                "or fill cmems_username/cmems_password in [CMEMS_SOURCES] of config.example.ini"
            )
        self.yesterday = (datetime.now(tz=timezone.utc) - timedelta(days=1)).strftime("%Y%m%d")

    @pytest.mark.integration
    def test_download_returns_true_for_recent_date(self) -> None:
        downloader = CMEMSDownloader(self.cfg, logger=self.logger)
        result = downloader.download(self.yesterday)
        self.assertTrue(result, f"CMEMSDownloader.download({self.yesterday!r}) returned False")

    @pytest.mark.integration
    def test_download_creates_nc_files_in_storage_dir(self) -> None:
        downloader = CMEMSDownloader(self.cfg, logger=self.logger)
        downloader.download(self.yesterday)
        nc_files = list(downloader.storage_dir.rglob("*.nc"))
        self.assertGreater(
            len(nc_files),
            0,
            f"No *.nc files found under {downloader.storage_dir} after download",
        )

    @pytest.mark.integration
    def test_timeout_is_respected(self) -> None:
        cfg_tight = configparser.ConfigParser()
        cfg_tight.read_dict({s: dict(self.cfg[s]) for s in self.cfg.sections()})
        cfg_tight["DOWNLOAD"]["download_timeout_seconds"] = "10"
        cfg_tight["DOWNLOAD"]["download_retry_count"] = "2"
        cfg_tight["DOWNLOAD"]["download_retry_delay_seconds"] = "2"

        captured: list[str] = []

        class _CapturingHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                captured.append(self.format(record))

        cap_handler = _CapturingHandler()
        cap_handler.setLevel(logging.DEBUG)

        test_logger = logging.getLogger("test_timeout_is_respected")
        test_logger.setLevel(logging.DEBUG)
        test_logger.addHandler(cap_handler)
        test_logger.addHandler(logging.StreamHandler(sys.stdout))

        downloader = CMEMSDownloader(cfg_tight, logger=test_logger)
        result = downloader.download("20260413")

        self.assertEqual(result, False, "download() should return False when all retries time out")

        joined = "\n".join(captured)
        self.assertTrue(
            any("timed out after 10s" in msg for msg in captured),
            f"Expected 'timed out after 10s' in logs; got:\n{joined}",
        )
        self.assertTrue(
            any("retry attempts exhausted" in msg for msg in captured),
            f"Expected 'retry attempts exhausted' in logs; got:\n{joined}",
        )


if __name__ == "__main__":
    unittest.main()
