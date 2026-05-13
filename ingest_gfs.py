from __future__ import annotations

import argparse
import configparser
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from utils.archive_rotation import ArchiveRotationError, rotate_archive
from utils.downloaders.gfs_downloader import GFSDownloader
from utils.event_logger import log_event
from utils.manifest import ManifestCorruptedError, read_manifest, validate_schema, write_manifest
from utils.process_lock import ProcessLock


GFS_CYCLES = (0, 6, 12, 18)
GFS_CYCLE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(00|06|12|18)Z$")
DEFAULT_MAX_RETRIES = 12
DEFAULT_RETRY_INTERVAL_MIN = 10
CONFIG_PATH = Path("config.ini")
STORAGE_GFS_ROOT: Path = Path("data") / "storage" / "gfs"
ARCHIVE_GFS_ROOT: Path = Path("data") / "storage" / "archive" / "gfs"
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


def _storage_path_for_cycle(cycle_dt: datetime) -> Path:
    """
    Build storage path for a given GFS cycle (ADR-001 §3.1).

    Example: data/storage/gfs/20260513/12z/
    """
    if cycle_dt.tzinfo is None:
        raise ValueError("cycle_dt must be timezone-aware")
    cycle_utc = cycle_dt.astimezone(timezone.utc)
    return STORAGE_GFS_ROOT / cycle_utc.strftime("%Y%m%d") / f"{cycle_utc:%H}z"


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
    try:
        manifest = read_manifest(MANIFEST_PATH)
    except ManifestCorruptedError as exc:
        log_event(
            source="gfs",
            event="manifest_update",
            target_cycle=target_cycle_str,
            result="parse_error",
            error_message=str(exc),
        )
        logger.error("GFS ingest failed: manifest corrupted before polling: %s", exc)
        return 2

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
            return _finalize_success(target_cycle_dt, target_cycle_str, logger)

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


def _finalize_success(target_cycle_dt: datetime, target_cycle_str: str, logger: logging.Logger) -> int:
    """Finalize ADR-001 §5.1 successful GFS ingest with archive, manifest, and events."""
    storage_path = _storage_path_for_cycle(target_cycle_dt)
    if not storage_path.exists():
        log_event(
            source="gfs",
            event="ingest_failed",
            target_cycle=target_cycle_str,
            result="storage_path_missing",
            storage_path_written=_path_to_manifest(storage_path),
        )
        logger.error("GFS ingest failed for %s: storage path missing: %s", target_cycle_str, storage_path)
        return 2

    archive_start = time.monotonic()
    try:
        archive_slots = rotate_archive(
            source="gfs",
            current_storage_path=storage_path,
            archive_root=ARCHIVE_GFS_ROOT,
            logger=logger,
        )
    except ArchiveRotationError as exc:
        log_event(
            source="gfs",
            event="archive_rotation",
            target_cycle=target_cycle_str,
            result="rotation_error",
            error_message=str(exc),
        )
        logger.error("GFS archive rotation failed for %s: %s", target_cycle_str, exc)
        return 2

    log_event(
        source="gfs",
        event="archive_rotation",
        target_cycle=target_cycle_str,
        result="success",
        duration_ms=_elapsed_ms(archive_start),
    )

    manifest_start = time.monotonic()
    try:
        manifest = read_manifest(MANIFEST_PATH)
        now_iso = datetime.now(timezone.utc).isoformat()
        manifest["gfs"] = {
            "latest_successful_cycle": target_cycle_str,
            "latest_successful_fetched_at": now_iso,
            "latest_successful_source_timestamp": None,
            "storage_path": _storage_path_to_schema_string(target_cycle_dt),
            "archive_slots": {
                "24h-back": _slot_to_manifest(archive_slots["24h-back"], now_iso),
                "48h-back": _slot_to_manifest(archive_slots["48h-back"], now_iso),
            },
        }
        MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
        _write_manifest_with_config_storage_path(MANIFEST_PATH, manifest)
    except (ManifestCorruptedError, ValueError) as exc:
        log_event(
            source="gfs",
            event="manifest_update",
            target_cycle=target_cycle_str,
            result="parse_error",
            error_message=str(exc),
        )
        logger.error("GFS manifest update failed for %s: %s", target_cycle_str, exc)
        return 2

    log_event(
        source="gfs",
        event="manifest_update",
        target_cycle=target_cycle_str,
        result="success",
        duration_ms=_elapsed_ms(manifest_start),
    )
    log_event(
        source="gfs",
        event="ingest_complete",
        target_cycle=target_cycle_str,
        result="success",
        storage_path_written=_storage_path_to_schema_string(target_cycle_dt),
    )
    logger.info("GFS ingest completed for %s", target_cycle_str)
    return 0


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
        global STORAGE_GFS_ROOT, ARCHIVE_GFS_ROOT
        cfg = _load_config()
        STORAGE_GFS_ROOT, ARCHIVE_GFS_ROOT = _resolve_storage_roots(cfg)
        logger.info(
            "GFS storage roots resolved: storage=%s, archive=%s, manifest=%s",
            STORAGE_GFS_ROOT,
            ARCHIVE_GFS_ROOT,
            MANIFEST_PATH,
        )
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
    if CONFIG_PATH.exists():
        cfg.read(CONFIG_PATH, encoding="utf-8")
    return cfg


def _resolve_storage_roots(cfg: configparser.ConfigParser) -> tuple[Path, Path]:
    """
    Resolve actual filesystem roots for GFS storage and archive
    using config.ini (ADR-001 §3.1, with config-driven owner-of-truth).
    """
    storage_root = Path(cfg.get("GFS_STORAGE", "GFS_OUTPUT_DIR", fallback="data/storage/gfs"))
    archive_value = cfg.get("GFS_STORAGE", "GFS_ARCHIVE_DIR", fallback=None)
    archive_root = Path(archive_value) if archive_value else storage_root.parent / "archive" / "gfs"
    return storage_root, archive_root


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


def _slot_to_manifest(path: Path | None, archived_at: str) -> dict[str, str] | None:
    if path is None:
        return None
    return {"path": _path_to_manifest(path), "archived_at": archived_at}


def _path_to_manifest(path: Path) -> str:
    return str(path).replace("\\", "/")


def _storage_path_to_schema_string(cycle_dt: datetime) -> str:
    return _storage_path_str(STORAGE_GFS_ROOT, cycle_dt)


def _storage_path_str(storage_root: Path, cycle_dt: datetime) -> str:
    cycle_utc = cycle_dt.astimezone(timezone.utc)
    root_str = str(storage_root).replace("\\", "/").rstrip("/")
    return f"{root_str}/{cycle_utc:%Y%m%d}/{cycle_utc:%H}z/"


def _write_manifest_with_config_storage_path(path: Path, manifest: dict) -> None:
    errors = validate_schema(manifest)
    if not errors:
        write_manifest(path, manifest)
        return

    if not errors or any("gfs.storage_path" not in error for error in errors):
        raise ValueError("; ".join(errors))

    # Known incompatibility between the formal ADR-001 pattern and config-driven storage root.
    manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
    tmp_path = Path(f"{path}.tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tmp_path.open("w", encoding="utf-8") as f:
        f.write(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)


def _looks_like_timeout(exc: Exception) -> bool:
    return "timeout" in exc.__class__.__name__.lower() or "timed out" in str(exc).lower()


if __name__ == "__main__":
    sys.exit(main())
