from __future__ import annotations

import configparser
import logging
import sys
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

PROJECT_ROOT = Path(__file__).resolve().parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _inject_utils_package_stubs() -> None:
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


def _make_cfg(enable_conversion: bool = True) -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    cfg.read_dict(
        {
            "GFS_SOURCES": {
                "GFS_MAIN_URL": "https://example.invalid",
                "GFS_MODEL_PATH_TEMPLATE": "gfs.{yyyymmdd}/{cycle}/atmos",
                "GFS_CYCLES": "00z,06z,12z,18z",
            },
            "GFS_DOWNLOAD": {
                "GFS_TIMEOUT_SECONDS": "10",
                "GFS_MAX_RETRIES": "1",
                "GFS_HTTP_RETRY_DELAY_SECONDS": "0",
            },
            "GFS_FORECAST": {
                "GFS_FORECAST_HOURS_START": "6",
                "GFS_FORECAST_HOURS_END": "6",
                "GFS_FORECAST_HOURS_STEP": "3",
                "GFS_VARIABLES": "var_TMP=on",
                "GFS_LEVELS": "lev_surface=on",
            },
            "GFS_STORAGE": {
                "GFS_WORK_DIR": "data/work/gfs",
                "GFS_OUTPUT_DIR": "data/storage/gfs",
            },
            "GFS_VALIDATION": {
                "GFS_ENABLE_CONVERSION_TO_NETCDF": "true" if enable_conversion else "false",
                "GFS_CHECK_FORECAST_COMPLETENESS": "true",
                "GFS_MIN_EXPECTED_FILES": "1",
            },
        }
    )
    return cfg


class TestGFSNetcdfConversion(unittest.TestCase):
    def setUp(self) -> None:
        self.logger = logging.getLogger("test_gfs_netcdf_conversion")
        self.logger.addHandler(logging.NullHandler())

    def test_netcdf_output_path_appends_nc(self) -> None:
        downloader = GFSDownloader(_make_cfg(enable_conversion=True), logger=self.logger)
        grib_path = Path("data/storage/gfs/20260416/00z/gfs.t00z.pgrb2.0p25.f006")
        self.assertEqual(
            downloader._netcdf_output_path(grib_path),
            Path("data/storage/gfs/20260416/00z/gfs.t00z.pgrb2.0p25.f006.nc"),
        )

    def test_ensure_netcdf_skips_when_disabled(self) -> None:
        downloader = GFSDownloader(_make_cfg(enable_conversion=False), logger=self.logger)
        with TemporaryDirectory() as tmp:
            grib_path = Path(tmp) / "gfs.t00z.pgrb2.0p25.f006"
            grib_path.write_bytes(b"grib")
            self.assertTrue(downloader._ensure_netcdf_for_grib(grib_path))

    def test_ensure_netcdf_uses_existing_netcdf(self) -> None:
        downloader = GFSDownloader(_make_cfg(enable_conversion=True), logger=self.logger)
        with TemporaryDirectory() as tmp:
            grib_path = Path(tmp) / "gfs.t00z.pgrb2.0p25.f006"
            grib_path.write_bytes(b"grib")
            nc_path = downloader._netcdf_output_path(grib_path)
            nc_path.write_bytes(b"netcdf")
            self.assertTrue(downloader._ensure_netcdf_for_grib(grib_path))

    def test_ensure_netcdf_calls_converter_when_missing(self) -> None:
        downloader = GFSDownloader(_make_cfg(enable_conversion=True), logger=self.logger)
        called: list[tuple[Path, Path]] = []

        def _fake_convert(grib_path: Path, nc_path: Path) -> bool:
            called.append((grib_path, nc_path))
            nc_path.write_bytes(b"netcdf")
            return True

        downloader._convert_grib_to_netcdf = _fake_convert  # type: ignore[method-assign]

        with TemporaryDirectory() as tmp:
            grib_path = Path(tmp) / "gfs.t00z.pgrb2.0p25.f006"
            grib_path.write_bytes(b"grib")
            self.assertTrue(downloader._ensure_netcdf_for_grib(grib_path))
            self.assertEqual(len(called), 1)
            self.assertTrue(downloader._netcdf_output_path(grib_path).exists())

    def test_convert_existing_skips_paths_with_nc_suffix_dt10_4(self) -> None:
        """Sidecar NetCDF must not match GRIB glob (DT-10-4)."""
        seen: list[str] = []

        def _track(grib_path: Path) -> bool:
            seen.append(grib_path.name)
            return True

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            day_dir = root / "20260415" / "00z"
            day_dir.mkdir(parents=True)
            grib = day_dir / "gfs.t00z.pgrb2.0p25.f006"
            grib.write_bytes(b"grib")
            sidecar = day_dir / "gfs.t00z.pgrb2.0p25.f006.nc"
            sidecar.write_bytes(b"netcdf")

            cfg = _make_cfg(enable_conversion=True)
            cfg.set("GFS_STORAGE", "GFS_OUTPUT_DIR", str(root))
            dl = GFSDownloader(cfg, logger=self.logger)
            dl._ensure_netcdf_for_grib = _track  # type: ignore[method-assign]

            n = dl.convert_existing("20260415", "00z")
            self.assertEqual(n, 1)
            self.assertEqual(seen, ["gfs.t00z.pgrb2.0p25.f006"])


if __name__ == "__main__":
    unittest.main()
