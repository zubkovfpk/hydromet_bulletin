"""
ingest_cmems.py — on-demand CMEMS wave data ingestion.
Автовычисляет run_hour и first_forecast_dt из текущего UTC времени.
Пишет результат в manifest.json (CMEMS блок).

Использование:
  python ingest_cmems.py
  python ingest_cmems.py --snapshot 2026-06-08
  python ingest_cmems.py --dry-run
"""

from __future__ import annotations

import argparse
import configparser
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from utils.downloaders.cmems_downloader import CMEMSDownloader
from utils.manifest import read_manifest, write_manifest

CONFIG_PATH = Path("config.ini")
MANIFEST_PATH = Path("storage") / "manifest.json"

DEFAULT_LOG_LEVEL = "INFO"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run CMEMS wave data ingestion")
    parser.add_argument("--snapshot", default=None, help="Target CMEMS layer date, format YYYY-MM-DD")
    parser.add_argument("--dry-run", action="store_true", help="Exercise without real downloads")
    parser.add_argument("--config", default=str(CONFIG_PATH), help="Path to config.ini")
    parser.add_argument("--log-level", default=DEFAULT_LOG_LEVEL, choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="Logging level")
    return parser.parse_args(argv)


def _resolve_cmems_run_params(snapshot_date: date) -> tuple[str, str, str]:
    """
    Возвращает (run_date_str, run_hour, first_forecast_dt) для snapshot_date.
    
    CMEMS публикует два run'а в сутки:
    - run_hour="00": данные за дату D, первый forecast slot = D+"00"
    - run_hour="12": данные за дату D, первый forecast slot = D+"12"
    
    Правило выбора последнего доступного run (UTC):
    - Если current_utc.hour >= 12: run_hour="00", run_date=today, fdt = run_date+"00"
    - Если current_utc.hour < 12: run_hour="12", run_date=yesterday, fdt = run_date+"12"
    """
    current_utc = datetime.now(timezone.utc)
    
    if current_utc.hour >= 12:
        run_hour = "00"
        run_date = snapshot_date
        first_forecast_dt = run_date.strftime("%Y%m%d") + "00"
    else:
        run_hour = "12"
        run_date = snapshot_date - timedelta(days=1)
        first_forecast_dt = run_date.strftime("%Y%m%d") + "12"
    
    return run_date.strftime("%Y-%m-%d"), run_hour, first_forecast_dt


def _load_config(config_path: Path) -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    cfg.read(config_path)
    return cfg


def _get_storage_path(cfg: configparser.ConfigParser) -> Path:
    """Возвращает путь к CMEMS storage из config.ini."""
    cmems_output_dir = cfg.get("STORAGE", "CMEMS_OUTPUT_DIR", fallback="data/storage/cmems")
    return Path(cmems_output_dir)


def run_ingest(
    snapshot_date: date,
    dry_run: bool,
    cfg: configparser.ConfigParser,
    logger: logging.Logger,
) -> int:
    """
    Run CMEMS ingestion for snapshot_date.
    
    Returns exit code: 0 (success), 2 (failure).
    """
    run_date_str, run_hour, first_forecast_dt = _resolve_cmems_run_params(snapshot_date)
    
    logger.info("CMEMS params: snapshot=%s, run_date=%s, run_hour=%s, first_forecast_dt=%s",
                snapshot_date, run_date_str, run_hour, first_forecast_dt)
    
    if dry_run:
        logger.info("Dry-run mode: skipping actual download")
        return 0
    
    storage_path = _get_storage_path(cfg)
    
    try:
        downloader = CMEMSDownloader(cfg, logger=logger)
        run_date_compact = run_date_str.replace("-", "")
        success = downloader.download(
            run_date=run_date_compact,
            run_hour=run_hour,
            first_forecast_dt=first_forecast_dt,
        )
        
        if not success:
            logger.error("CMEMS download failed")
            return 2
        
        # Обновить manifest
        manifest = read_manifest(MANIFEST_PATH)
        
        cmems_storage_path = storage_path / run_date_compact
        
        manifest["cmems"] = {
            "latest_successful_layer_date": snapshot_date.isoformat(),
            "latest_successful_fetched_at": datetime.now(timezone.utc).isoformat(),
            "latest_successful_source_timestamp": None,  # CMEMS toolbox does not expose source publication timestamp
            "storage_path": str(cmems_storage_path),
            "archive_slots": {"24h-back": None, "48h-back": None},  # TODO: implement archive rotation
        }
        
        write_manifest(MANIFEST_PATH, manifest)
        logger.info("CMEMS manifest updated: %s", snapshot_date)
        
    except Exception as exc:
        logger.exception("CMEMS ingestion failed: %s", exc)
        return 2
    
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger = logging.getLogger(__name__)
    
    try:
        config_path = Path(args.config)
        cfg = _load_config(config_path)
        
        if args.snapshot:
            snapshot_date = date.fromisoformat(args.snapshot)
        else:
            snapshot_date = datetime.now(timezone.utc).date()
        
        return run_ingest(snapshot_date, args.dry_run, cfg, logger)
        
    except ValueError as exc:
        logger.error("Invalid argument: %s", exc)
        return 1
    except Exception as exc:
        logger.exception("Unexpected error: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())

