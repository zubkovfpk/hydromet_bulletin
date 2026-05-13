from __future__ import annotations

import argparse
import configparser
import logging
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from utils.archive_rotation import rotate_archive
from utils.downloaders.gfs_downloader import GFSDownloader
from utils.event_logger import log_event
from utils.manifest import read_manifest, write_manifest
from utils.process_lock import ProcessLock


GFS_CYCLES = (0, 6, 12, 18)
GFS_CYCLE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(00|06|12|18)Z$")
DEFAULT_MAX_RETRIES = 12
DEFAULT_RETRY_INTERVAL_MIN = 10
MANIFEST_PATH = Path("storage") / "manifest.json"
LOCK_PATH = Path("storage") / ".ingest_gfs.lock"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run GFS ingestion polling loop")
    parser.add_argument("--cycle", default=None, help="Target GFS cycle, format YYYY-MM-DDTHHZ")
    parser.add_argument("--max-retries", type=_positive_int, default=DEFAULT_MAX_RETRIES)
    parser.add_argument("--retry-interval-min", type=_non_negative_int, default=DEFAULT_RETRY_INTERVAL_MIN)
    parser.add_argument("--force", action="store_true", help="Ignore already-ingested manifest state")
    parser.add_argument("--dry-run", action="store_true", help="Exercise polling without real downloads")
    return parser.parse_args(argv)


def resolve_target_cycle(now_utc: datetime, override: str | None) -> datetime:
    """
    Return UTC datetime aligned to GFS cycle (00/06/12/18Z).

    If override is set, parse strictly 'YYYY-MM-DDTHHZ'. Otherwise floor
    now_utc to the most recent past cycle (ADR-001 §5.1, ADR-001 §6.1).
    """
    if override is not None:
        match = GFS_CYCLE_RE.fullmatch(override)
        if match is None:
            raise ValueError("expected YYYY-MM-DDTHHZ where HH is one of 00, 06, 12, 18")
        return datetime(
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
            int(match.group(4)),
            tzinfo=timezone.utc,
        )

    if now_utc.tzinfo is None:
        raise ValueError("now_utc must be timezone-aware")

    utc_now = now_utc.astimezone(timezone.utc)
    cycle_hour = max(hour for hour in GFS_CYCLES if hour <= utc_now.hour)
    return utc_now.replace(hour=cycle_hour, minute=0, second=0, microsecond=0)


def format_cycle(cycle_dt: datetime) -> str:
    """Return 'YYYY-MM-DDTHHZ' (UTC) representation used in manifest/events."""
    if cycle_dt.tzinfo is None:
        raise ValueError("cycle_dt must be timezone-aware")
    cycle_utc = cycle_dt.astimezone(timezone.utc)
    if cycle_utc.hour not in GFS_CYCLES:
        raise ValueError("cycle_dt hour must be one of 00, 06, 12, 18 UTC")
    return cycle_utc.strftime("%Y-%m-%dT%HZ")


def _attempt_download(
    cycle_dt: datetime,
    *,
    dry_run: bool,
    logger: logging.Logger,
) -> tuple[str, int | None, int | None]:
    """
    Run a single download attempt against NOMADS via existing GFS downloader.

    Returns
    -------
    result : str
        One of: "success", "not_ready", "network_error", "timeout".
    http_status : int | None
        HTTP status code if applicable.
    latency_ms : int | None
        Elapsed time of this attempt, in ms.
    """
    if dry_run:
        return "not_ready", 404, 1

    start = time.monotonic()
    try:
        cfg = _load_config()
        downloader = GFSDownloader(cfg, logger=logger)
        cycle_utc = cycle_dt.astimezone(timezone.utc)
        date = cycle_utc.strftime("%Y%m%d")
        cycle = cycle_utc.strftime("%Hz")
        success = downloader.download(date=date, cycle=cycle)
    except TimeoutError:
        return "timeout", None, _elapsed_ms(start)
    except OSError:
        logger.exception("GFS download attempt failed with network error")
        return "network_error", None, _elapsed_ms(start)
    except Exception as exc:
        if _looks_like_timeout(exc):
            return "timeout", None, _elapsed_ms(start)
        logger.exception("GFS download attempt failed")
        return "network_error", None, _elapsed_ms(start)

    return ("success" if success else "not_ready"), None, _elapsed_ms(start)


def run_ingest(
    target_cycle_dt: datetime,
    *,
    max_retries: int,
    retry_interval_min: int,
    force: bool,
    dry_run: bool,
    logger: logging.Logger,
) -> int:
    """
    Run ADR-001 §5.1 GFS polling loop.

    Returns process exit code: 0 (success or nothing-to-do), 2 (failure).
    """
    target_cycle_str = format_cycle(target_cycle_dt)
    manifest = read_manifest(MANIFEST_PATH)
    gfs_manifest = manifest.get("gfs")

    if (
        not force
        and isinstance(gfs_manifest, dict)
        and gfs_manifest.get("latest_successful_cycle") == target_cycle_str
    ):
        log_event(
            source="gfs",
            event="ingest_skip",
            target_cycle=target_cycle_str,
            result="already_ingested",
        )
        logger.info("GFS ingest skipped: cycle already ingested (%s)", target_cycle_str)
        return 0

    for attempt in range(1, max_retries + 1):
        result, http_status, latency_ms = _attempt_download(
            target_cycle_dt,
            dry_run=dry_run,
            logger=logger,
        )
        log_event(
            source="gfs",
            event="poll_attempt",
            target_cycle=target_cycle_str,
            result=result,
            http_status=http_status,
            latency_ms=latency_ms,
            retry_number=attempt,
        )

        if result == "success":
            log_event(
                source="gfs",
                event="ingest_complete_stub",
                target_cycle=target_cycle_str,
                result="success_pending_manifest",
            )
            logger.info("GFS ingest succeeded for %s; manifest update pending next step", target_cycle_str)
            return 0

        if attempt < max_retries:
            time.sleep(retry_interval_min * 60)

    log_event(
        source="gfs",
        event="ingest_failed",
        target_cycle=target_cycle_str,
        result="retries_exhausted",
    )
    logger.error("GFS ingest failed for %s: retries exhausted", target_cycle_str)
    return 2


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logger = _build_logger()
    target_cycle_str: str | None = None

    try:
        now_utc = datetime.now(timezone.utc)
        target_cycle_dt = resolve_target_cycle(now_utc, args.cycle)
        target_cycle_str = format_cycle(target_cycle_dt)
    except ValueError as exc:
        logger.error("Invalid --cycle: %s", exc)
        return 2

    try:
        LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        with ProcessLock(str(LOCK_PATH)):
            return run_ingest(
                target_cycle_dt,
                max_retries=args.max_retries,
                retry_interval_min=args.retry_interval_min,
                force=args.force,
                dry_run=args.dry_run,
                logger=logger,
            )
    except Exception as exc:
        log_event(
            source="gfs",
            event="ingest_failed",
            target_cycle=target_cycle_str,
            result="unhandled_exception",
            error_message=str(exc),
        )
        logger.exception("GFS ingest failed with unhandled exception")
        return 2


def _build_logger() -> logging.Logger:
    logger = logging.getLogger("ingest_gfs")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    return logger


def _load_config() -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    config_path = Path("config.ini")
    if not config_path.exists():
        config_path = Path("config.example.ini")
    read_ok = cfg.read(config_path, encoding="utf-8")
    if not read_ok:
        raise FileNotFoundError(f"Config file is not readable: {config_path}")
    return cfg


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be > 0")
    return parsed


def _non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be >= 0")
    return parsed


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


def _looks_like_timeout(exc: Exception) -> bool:
    return "timeout" in exc.__class__.__name__.lower() or "timed out" in str(exc).lower()


def _future_step_dependencies() -> tuple[object, object]:
    return write_manifest, rotate_archive


if __name__ == "__main__":
    sys.exit(main())
