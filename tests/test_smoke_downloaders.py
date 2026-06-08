# Smoke tests for downloader initialization (no HTTP).
from __future__ import annotations

import configparser
import logging
import sys
import types
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.example.ini"

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

from utils.downloaders.cmems_downloader import CMEMSDownloader
from utils.downloaders.gfs_downloader import GFSDownloader


def _load_example_config() -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    read = cfg.read(CONFIG_PATH, encoding="utf-8")
    if not read:
        raise FileNotFoundError(f"Cannot read config: {CONFIG_PATH}")
    return cfg


class TestSmokeDownloaders(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cfg = _load_example_config()
        cls.logger = logging.getLogger("test_smoke_downloaders")
        cls.logger.addHandler(logging.NullHandler())

    def test_cmems_downloader_init_from_example_config(self) -> None:
        d = CMEMSDownloader(self.cfg, logger=self.logger)
        self.assertTrue(self.cfg.get("CMEMS_SOURCES", "cmems_base_url", fallback="").strip())
        self.assertTrue(d.auth_method)
        self.assertIsNotNone(d.timeout_seconds)
        self.assertGreater(d.timeout_seconds, 0)
        self.assertIsNotNone(d.max_retries)
        self.assertGreaterEqual(d.max_retries, 0)
        self.assertTrue(str(d.storage_dir).strip())
        self.assertTrue(d.file_patterns_raw.strip())

    def test_gfs_downloader_init_from_example_config(self) -> None:
        d = GFSDownloader(self.cfg, logger=self.logger)
        self.assertTrue(d.main_url.strip())
        self.assertIsNotNone(d.timeout_seconds)
        self.assertGreater(d.timeout_seconds, 0)
        self.assertIsNotNone(d.max_retries)
        self.assertGreaterEqual(d.max_retries, 0)
        self.assertTrue(str(d.work_dir).strip())
        self.assertGreater(d.hours_end, d.hours_start)
        self.assertTrue(d.variables_str.strip())
        self.assertTrue(d.levels_str.strip())
        self.assertEqual(d.hours_step, 3)
        self.assertEqual(d.hours_start, 6)
        self.assertEqual(d.hours_end, 123)


if __name__ == "__main__":
    unittest.main()
