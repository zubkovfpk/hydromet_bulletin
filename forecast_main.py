"""
Unified on-demand forecast entrypoint per ADR-001.

This module is the single CLI entrypoint for on-demand ingestion flow and will
replace `forecast_morning.py` / `forecast_evening.py`.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

MSK_TZ = ZoneInfo("Europe/Moscow")
UTC_TZ = timezone.utc
DEFAULT_TIMEOUT_MINUTES = 360
DEFAULT_POLLING_MINUTES = 10
GFS_LAG_HOURS = 6
CMEMS_LAG_HOURS = 12
GFS_CYCLES_UTC = (0, 6, 12, 18)
CMEMS_RELEASE_HOUR_UTC = 12

logger = logging.getLogger(__name__)


def _bounded_int(value: str, *, minimum: int, maximum: int, field_name: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{field_name} must be an integer.") from exc
    if parsed < minimum or parsed > maximum:
        raise argparse.ArgumentTypeError(
            f"{field_name} must be between {minimum} and {maximum}."
        )
    return parsed


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="On-demand forecast entrypoint (ADR-001)."
    )
    parser.add_argument("--date", required=True, type=str, help="Date in YYYY-MM-DD.")
    parser.add_argument("--time", required=True, type=str, help="Time in HH:MM.")
    parser.add_argument(
        "--tz",
        default="MSK",
        choices=["MSK", "UTC"],
        help="Input timezone (MSK or UTC).",
    )
    parser.add_argument(
        "--timeout-minutes",
        default=DEFAULT_TIMEOUT_MINUTES,
        type=lambda v: _bounded_int(
            v,
            minimum=10,
            maximum=720,
            field_name="timeout-minutes",
        ),
        help="Overall timeout in minutes (10..720).",
    )
    parser.add_argument(
        "--polling-minutes",
        default=DEFAULT_POLLING_MINUTES,
        type=lambda v: _bounded_int(
            v,
            minimum=1,
            maximum=60,
            field_name="polling-minutes",
        ),
        help="Polling interval in minutes (1..60).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print resolved parameters and exit.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity.",
    )
    return parser.parse_args(argv)


def msk_to_utc(date_str: str, time_str: str, tz_name: str) -> datetime:
    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"Invalid --date format/value '{date_str}', expected YYYY-MM-DD.") from exc

    try:
        time_obj = datetime.strptime(time_str, "%H:%M").time()
    except ValueError as exc:
        raise ValueError(f"Invalid --time format/value '{time_str}', expected HH:MM.") from exc

    naive_dt = datetime.combine(date_obj, time_obj)

    if tz_name == "MSK":
        local_dt = naive_dt.replace(tzinfo=MSK_TZ)
        return local_dt.astimezone(UTC_TZ)
    if tz_name == "UTC":
        return naive_dt.replace(tzinfo=UTC_TZ)
    raise ValueError(f"Unsupported timezone '{tz_name}'. Supported values: MSK, UTC.")


def _ensure_utc_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("request_time_utc must be timezone-aware.")
    return dt.astimezone(UTC_TZ)


def resolve_gfs_cycle(request_time_utc: datetime) -> datetime:
    """
    Return timezone-aware UTC datetime of nearest available GFS cycle.
    """
    request_utc = _ensure_utc_aware(request_time_utc)
    effective = request_utc - timedelta(hours=GFS_LAG_HOURS)

    eligible_hours = [h for h in GFS_CYCLES_UTC if h <= effective.hour]
    if eligible_hours:
        cycle_hour = max(eligible_hours)
        cycle_day = effective.date()
    else:
        cycle_hour = max(GFS_CYCLES_UTC)
        cycle_day = effective.date() - timedelta(days=1)

    return datetime(
        cycle_day.year,
        cycle_day.month,
        cycle_day.day,
        cycle_hour,
        0,
        tzinfo=UTC_TZ,
    )


def resolve_cmems_layer(request_time_utc: datetime) -> date:
    """
    Return date of available CMEMS daily layer for request time.
    """
    request_utc = _ensure_utc_aware(request_time_utc)
    effective = request_utc - timedelta(hours=CMEMS_LAG_HOURS)
    release_time = time(CMEMS_RELEASE_HOUR_UTC, 0)

    if effective.time() >= release_time:
        return effective.date()
    return effective.date() - timedelta(days=1)


def setup_logging(level_name: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level_name, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        setup_logging(args.log_level)

        resolved_utc = msk_to_utc(args.date, args.time, args.tz)
        logger.info(
            "Input params: date=%s time=%s tz=%s timeout_minutes=%d polling_minutes=%d dry_run=%s",
            args.date,
            args.time,
            args.tz,
            args.timeout_minutes,
            args.polling_minutes,
            args.dry_run,
        )
        logger.info("Resolved UTC datetime: %s", resolved_utc.isoformat())
        resolved_gfs_cycle = resolve_gfs_cycle(resolved_utc)
        resolved_cmems_layer = resolve_cmems_layer(resolved_utc)
        logger.info("Resolved GFS cycle UTC: %s", resolved_gfs_cycle.isoformat())
        logger.info("Resolved CMEMS layer date: %s", resolved_cmems_layer.isoformat())

        if args.dry_run:
            print("[dry-run] forecast_main resolved parameters:")
            print(f"  input_date: {args.date}")
            print(f"  input_time: {args.time}")
            print(f"  input_tz: {args.tz}")
            print(f"  UTC datetime: {resolved_utc.isoformat()}")
            print(f"  gfs_cycle: {resolved_gfs_cycle.isoformat()}")
            print(f"  cmems_layer: {resolved_cmems_layer.isoformat()}")
            print(f"  gfs_lag: {GFS_LAG_HOURS}h")
            print(f"  cmems_lag: {CMEMS_LAG_HOURS}h")
            print(f"  timeout_minutes: {args.timeout_minutes}")
            print(f"  polling_minutes: {args.polling_minutes}")
            return 0

        logger.warning("resolve_cycles + polling not yet implemented (15.D.2/15.D.3)")
        return 0
    except ValueError as exc:
        logger.error("%s", exc)
        return 2
    except KeyboardInterrupt:
        logger.warning("Interrupted by user.")
        return 130
    except Exception:
        logger.exception("Unhandled error in forecast_main.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
