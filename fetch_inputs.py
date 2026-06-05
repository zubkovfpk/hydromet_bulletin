# AUTO-GENERATED SKELETON — review before use.
"""Entry point for data ingestion wrappers (CMEMS + GFS)."""

from __future__ import annotations

import argparse
import configparser
import logging
import logging.handlers
import sys
from pathlib import Path

from utils.downloaders.cmems_downloader import CMEMSDownloader
from utils.downloaders.gfs_downloader import GFSDownloader


LOG_PATH = Path("logs") / "fetch_inputs.log"


def _setup_logging() -> logging.Logger:
    """Configure logging to console and logs/fetch_inputs.log."""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(),
            logging.handlers.RotatingFileHandler(
                LOG_PATH, maxBytes=5 * 1024 * 1024, backupCount=7, encoding="utf-8"
            ),
        ],
    )
    return logging.getLogger(__name__)


def _load_config(config_path: str) -> configparser.ConfigParser:
    """Load config file used by ingestion layer."""
    cfg = configparser.ConfigParser()
    read_ok = cfg.read(config_path, encoding="utf-8")
    if not read_ok:
        raise FileNotFoundError(f"Config file is not readable: {config_path}")
    return cfg


def _validate_sections(cfg: configparser.ConfigParser) -> None:
    """Ensure required sections exist for the wrapper flow."""
    required_sections = ("CMEMS_SOURCES", "CMEMS_FORECAST", "GFS_SOURCES", "GFS_DOWNLOAD", "GFS_FORECAST")
    missing = [name for name in required_sections if not cfg.has_section(name)]
    if missing:
        raise KeyError(f"Missing required config sections: {', '.join(missing)}")


def main() -> int:
    """Run ingestion wrappers and return process exit code."""
    parser = argparse.ArgumentParser(description="Fetch input data for bulletin pipeline")
    parser.add_argument("--config", default="config.ini", help="Path to config.ini")
    parser.add_argument("--date", default=None, help="Run date in YYYYMMDD")
    parser.add_argument("--cycle", default=None, help="GFS cycle (00z/06z/12z/18z)")
    parser.add_argument(
        "--cmems-run-hour",
        default=None,
        choices=["00", "12"],
        help="CMEMS model run hour (UTC); required for CMEMS get() regex until DT-14-Z",
    )
    parser.add_argument(
        "--cmems-first-forecast-dt",
        default=None,
        help="First forecast slot YYYYMMDDHH (UTC, hour 00 or 12); required with --cmems-run-hour",
    )
    args = parser.parse_args()

    logger = _setup_logging()

    try:
        logger.info("=== fetch_inputs: start ===")
        cfg = _load_config(args.config)
        _validate_sections(cfg)

        run_date = args.date or cfg.get("General", "target_date", fallback="").strip()
        if not run_date:
            from datetime import date
            run_date = date.today().strftime("%Y%m%d")
        gfs_cycle = args.cycle or cfg.get("GFS_SOURCES", "GFS_CYCLES", fallback="00z").split(",")[0].strip()

        cmems = CMEMSDownloader(cfg, logger=logger)
        gfs = GFSDownloader(cfg, logger=logger)

        cmems_ok = cmems.download(
            run_date,
            run_hour=args.cmems_run_hour,
            first_forecast_dt=args.cmems_first_forecast_dt,
        )
        gfs_ok = gfs.download(date=run_date, cycle=gfs_cycle)

        if cmems_ok and gfs_ok:
            logger.info("=== fetch_inputs: completed successfully ===")
            return 0

        logger.error("=== fetch_inputs: completed with ingestion errors ===")
        return 2

    except Exception:
        logger.exception("fetch_inputs failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
