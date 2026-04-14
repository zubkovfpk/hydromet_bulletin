# Integration tests for GFSDownloader — require real network access.
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
CONFIG_PATH = PROJECT_ROOT / os.environ.get("GFS_TEST_CONFIG", "config.example.ini")

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

from utils.downloaders.gfs_downloader import GFSDownloader  # noqa: E402


def _load_example_config() -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    read = cfg.read(CONFIG_PATH, encoding="utf-8")
    if not read:
        raise FileNotFoundError(f"Cannot read config: {CONFIG_PATH}")
    return cfg


def _make_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(logging.DEBUG)
        logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    return logger


@pytest.mark.integration
class TestGFSIntegration(unittest.TestCase):

    def setUp(self) -> None:
        self.cfg = _load_example_config()
        self.logger = _make_logger("test_integration_gfs")
        self.yesterday = (datetime.now(tz=timezone.utc) - timedelta(days=1)).strftime("%Y%m%d")
        self.cycle = "00z"

    @pytest.mark.integration
    def test_download_returns_true_for_recent_date(self) -> None:
        downloader = GFSDownloader(self.cfg, logger=self.logger)
        result = downloader.download(self.yesterday, self.cycle)
        self.assertTrue(result, f"GFSDownloader.download({self.yesterday!r}, {self.cycle!r}) returned False")

    @pytest.mark.integration
    def test_download_creates_grib2_files_in_storage_dir(self) -> None:
        downloader = GFSDownloader(self.cfg, logger=self.logger)
        downloader.download(self.yesterday, self.cycle)

        # Downloader writes into work_dir; filenames follow NOMADS 'pgrb2' naming.
        grib2_files = list(downloader.work_dir.rglob("*.grib2"))
        if not grib2_files:
            grib2_files = [p for p in downloader.work_dir.rglob("*") if p.is_file() and "pgrb2" in p.name]

        self.assertGreater(
            len(grib2_files),
            0,
            f"No GRIB2-like files found under {downloader.work_dir} after download",
        )

    @pytest.mark.integration
    def test_retry_on_bad_url(self) -> None:
        cfg_bad = configparser.ConfigParser()
        cfg_bad.read_dict({s: dict(self.cfg[s]) for s in self.cfg.sections()})

        # Keep this test fast: one forecast step, short timeout, quick retries.
        cfg_bad["GFS_FORECAST"]["GFS_FORECAST_HOURS_START"] = "6"
        cfg_bad["GFS_FORECAST"]["GFS_FORECAST_HOURS_END"] = "6"
        cfg_bad["GFS_FORECAST"]["GFS_FORECAST_HOURS_STEP"] = "3"
        cfg_bad["GFS_DOWNLOAD"]["GFS_TIMEOUT_SECONDS"] = "5"
        cfg_bad["GFS_DOWNLOAD"]["GFS_MAX_RETRIES"] = "2"
        cfg_bad["GFS_DOWNLOAD"]["GFS_HTTP_RETRY_DELAY_SECONDS"] = "0"

        captured: list[str] = []

        class _CapturingHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                captured.append(self.format(record))

        cap_handler = _CapturingHandler()
        cap_handler.setLevel(logging.DEBUG)

        test_logger = logging.getLogger("test_retry_on_bad_url")
        test_logger.setLevel(logging.DEBUG)
        test_logger.addHandler(cap_handler)
        test_logger.addHandler(logging.StreamHandler(sys.stdout))

        downloader = GFSDownloader(cfg_bad, logger=test_logger)

        # "monkeypatch" equivalent: override instance field.
        downloader.main_url = "http://127.0.0.1:9/definitely-not-working"

        result = downloader.download(self.yesterday, self.cycle)
        self.assertEqual(result, False, "download() should return False when URL is unreachable")

        joined = "\n".join(captured)
        self.assertTrue(
            any("attempt=1/" in msg for msg in captured) and any("attempt=2/" in msg for msg in captured),
            f"Expected retries to happen (attempt=1 and attempt=2) in logs; got:\n{joined}",
        )
        self.assertTrue(
            any("retries exhausted" in msg for msg in captured),
            f"Expected 'retries exhausted' in logs; got:\n{joined}",
        )


if __name__ == "__main__":
    unittest.main()
