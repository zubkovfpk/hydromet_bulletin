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
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

from utils.collect_meteo_data import collect_meteo_data
from utils.collect_wave_data import collect_wave_data
from utils.doc_builder import create_bulletin_doc as build_doc
from utils.manifest import read_manifest
from utils.precip_statistics import precip_statistics
from utils.temp_statistics import temp_statistics_morning as temp_statistics
from utils.validate_outputs import NOMINAL_TOL_HOURS, assert_valid_for_bulletin
from utils.wind_statistics import wind_statistics

MSK_TZ = ZoneInfo("Europe/Moscow")
UTC_TZ = timezone.utc
DEFAULT_TIMEOUT_MINUTES = 360
DEFAULT_POLLING_MINUTES = 10
GFS_LAG_HOURS = 6
CMEMS_LAG_HOURS = 12
GFS_CYCLES_UTC = (0, 6, 12, 18)
CMEMS_RELEASE_HOUR_UTC = 12
OUTPUT_DIR_DEFAULT = Path("output")
MANIFEST_PATH = Path("storage") / "manifest.json"
DEFAULT_FORECAST_HOURS = 120

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
        help="Print resolved parameters and pipeline plan, then exit.",
    )
    parser.add_argument(
        "--no-email",
        action="store_true",
        help=(
            "Build bulletin but skip email delivery. In 15.E.1 this flag is "
            "effectively a no-op (email is added in 15.E.2), but accepted "
            "to keep CLI stable."
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing output .docx if it already exists.",
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


def build_output_filename(
    start_dt_utc: datetime,
    request_dt_utc: datetime,
    output_dir: Path,
    *,
    force: bool = False,
) -> Path:
    """
    Build the path for the bulletin .docx file according to DT-14-T / ADR-001 §5.4.

    Base name: 'Прогноз_{YYYYMMDD}_{HHMM}.docx'
        where YYYYMMDD and HHMM are derived from start_dt_utc
        converted into MSK (Europe/Moscow).
    Collision: if the base file exists and force is False,
        append suffix '_req-{HHMM}' (HHMM from request_dt_utc in MSK).
        If collision persists even with suffix -> raise FileExistsError.
    Force: if force is True, return the base path unconditionally
        (caller is expected to overwrite).
    """
    if start_dt_utc.tzinfo is None:
        raise ValueError("start_dt_utc must be timezone-aware")
    if request_dt_utc.tzinfo is None:
        raise ValueError("request_dt_utc must be timezone-aware")

    output_dir.mkdir(parents=True, exist_ok=True)
    start_msk = start_dt_utc.astimezone(MSK_TZ)
    req_msk = request_dt_utc.astimezone(MSK_TZ)

    stem = f"Прогноз_{start_msk.strftime('%Y%m%d')}_{start_msk.strftime('%H%M')}"
    base_path = output_dir / f"{stem}.docx"
    if force or not base_path.exists():
        return base_path

    suffixed_path = output_dir / f"{stem}_req-{req_msk.strftime('%H%M')}.docx"
    if suffixed_path.exists():
        raise FileExistsError(
            "Output filename collision: "
            f"base path exists ({base_path}) and suffixed path exists ({suffixed_path})"
        )
    return suffixed_path


def setup_logging(level_name: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level_name, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def _format_cycle_for_events(cycle_dt: datetime) -> str:
    cycle_utc = cycle_dt.astimezone(UTC_TZ)
    return cycle_utc.strftime("%Y-%m-%dT%HZ")


def _resolve_storage_paths(
    manifest: dict[str, Any],
    gfs_cycle: datetime,
    cmems_layer: date,
    logger: logging.Logger,
) -> tuple[Path | None, Path | None]:
    """
    Read storage paths from manifest, when available.

    Returns
    -------
    (gfs_storage_path, cmems_storage_path)
        Both may be None if the manifest has no GFS/CMEMS block yet.
    """
    gfs_storage_path: Path | None = None
    cmems_storage_path: Path | None = None

    gfs_block = manifest.get("gfs")
    if isinstance(gfs_block, dict):
        manifest_cycle = gfs_block.get("latest_successful_cycle")
        resolved_cycle = _format_cycle_for_events(gfs_cycle)
        if manifest_cycle != resolved_cycle:
            logger.warning(
                "manifest GFS cycle != resolved cycle (manifest=%s; resolved=%s)",
                manifest_cycle,
                resolved_cycle,
            )
        storage_path = gfs_block.get("storage_path")
        if isinstance(storage_path, str):
            gfs_storage_path = Path(storage_path)
            logger.info("using GFS storage from manifest: %s", storage_path)

    cmems_block = manifest.get("cmems")
    if isinstance(cmems_block, dict):
        manifest_layer = cmems_block.get("latest_successful_layer_date")
        resolved_layer = cmems_layer.isoformat()
        if manifest_layer != resolved_layer:
            logger.warning(
                "manifest CMEMS layer != resolved layer (manifest=%s; resolved=%s)",
                manifest_layer,
                resolved_layer,
            )
        storage_path = cmems_block.get("storage_path")
        if isinstance(storage_path, str):
            cmems_storage_path = Path(storage_path)
            logger.info("using CMEMS storage from manifest: %s", storage_path)

    return gfs_storage_path, cmems_storage_path


def _run_pipeline(
    *,
    resolved_utc: datetime,
    gfs_cycle: datetime,
    cmems_layer: date,
    output_path: Path,
    logger: logging.Logger,
    dry_run: bool,
) -> None:
    """
    Glue existing processing modules under ADR-001 Scenario X.

    In dry-run mode no processing functions are called and no files are written.
    """
    cycle = f"{gfs_cycle.astimezone(UTC_TZ):%H}z"
    gfs_run_date = gfs_cycle.astimezone(UTC_TZ).strftime("%Y%m%d")
    cmems_run_date = cmems_layer.strftime("%Y%m%d")

    if dry_run:
        _emit_pipeline_plan(
            cycle=cycle,
            gfs_run_date=gfs_run_date,
            cmems_run_date=cmems_run_date,
            output_path=output_path,
        )
        logger.info("forecast_main: dry-run pipeline plan emitted; no files written")
        return

    logger.info(
        "forecast_main: pipeline start (cycle=%s, layer=%s, output=%s)",
        cycle,
        cmems_layer.isoformat(),
        output_path,
    )
    logger.info("forecast_main: pipeline step 1/5 collect_meteo_data run_date=%s cycle=%s", gfs_run_date, cycle)
    meteo = collect_meteo_data(run_date=gfs_run_date, cycle=cycle)

    logger.info("forecast_main: pipeline step 2/5 collect_wave_data run_date=%s", cmems_run_date)
    wave, start_date, end_date = collect_wave_data(run_date=cmems_run_date)

    logger.info("forecast_main: pipeline step 3/5 assert_valid_for_bulletin")
    assert_valid_for_bulletin(
        meteo_data=meteo,
        wave_data=(wave, start_date, end_date),
        strict=True,
        forecast_hours=DEFAULT_FORECAST_HOURS,
        tol_hours=NOMINAL_TOL_HOURS,
    )

    logger.info("forecast_main: pipeline step 4/5 statistics")
    days = _build_bulletin_days(meteo, wave, start_date, end_date, resolved_utc)

    logger.info("forecast_main: pipeline step 5/5 build_doc")
    header_date = resolved_utc.astimezone(MSK_TZ).strftime("от %d.%m.%Y %H:%M")
    build_doc(
        output_path=str(output_path),
        bulletin_type="on-demand",
        header_title="ГИДРОМЕТЕОРОЛОГИЧЕСКИЙ БЮЛЛЕТЕНЬ",
        header_date_line=header_date,
        days=days,
    )
    logger.info("forecast_main: bulletin written to %s", output_path)
    logger.info("forecast_main: email skipped (--no-email or 15.E.1 default)")


def _emit_pipeline_plan(*, cycle: str, gfs_run_date: str, cmems_run_date: str, output_path: Path) -> None:
    print("[dry-run] pipeline plan:")
    print(f"1) collect_meteo_data(...): cycle={cycle}, rundate={gfs_run_date}")
    print(f"2) collect_wave_data(...): rundate={cmems_run_date}")
    print("3) assert_valid_for_bulletin(meteo, wave, strict=True)")
    print("4) temp_statistics / wind_statistics / precip_statistics")
    print(f"5) build_doc(...) -> {output_path}")
    print("email: skipped (15.E.1; email layer added in 15.E.2)")


def _build_bulletin_days(
    meteo: dict[str, Any],
    wave: Any,
    start_date: datetime,
    end_date: datetime,
    resolved_utc: datetime,
) -> list[dict[str, str]]:
    n_days = min(int((end_date - start_date).days) + 1, 5)
    if n_days <= 0:
        n_days = 1

    start_msk = resolved_utc.astimezone(MSK_TZ)
    days: list[dict[str, str]] = []
    for index in range(n_days):
        period_start = start_msk + timedelta(days=index)
        period_end = start_msk + timedelta(days=index + 1)
        period_label = f"С {period_start:%H:%M %d.%m.%Y} до {period_end:%H:%M %d.%m.%Y}"

        wind_dir, wind_min, wind_max = wind_statistics(
            meteo["U_wind"][:, :, index],
            meteo["V_wind"][:, :, index],
        )
        gust = int(round(float(np.nanmax(meteo["Wind_Gust"][:, :, index]))))
        precipitation = precip_statistics(
            meteo["Freeze_Rain"][:, :, index],
            meteo["Ice_Pell"][:, :, index],
            meteo["Rain"][:, :, index],
            meteo["Snow"][:, :, index],
        )
        vis_min = int(round(float(np.nanmin(meteo["Vis"][:, :, index])) / 1000))
        vis_max = int(round(float(np.nanmax(meteo["Vis"][:, :, index])) / 1000))
        wave_min = round(float(np.nanmin(wave[:, :, index])), 1)
        wave_max = round(float(np.nanmax(wave[:, :, index])), 1)
        temperature = temp_statistics(
            meteo["Temp"][:, :, index],
            meteo["Temp"][:, :, index + 1],
        )
        body = (
            f"Ветер {wind_dir} {wind_min}-{wind_max} м/с, "
            f"возможны порывы до {gust} м/с. "
            f"{precipitation} "
            f"Видимость {vis_min}-{vis_max} км. "
            f"Высота волны {wave_min}-{wave_max} м. "
            f"{temperature}"
        )
        days.append({"period_label": period_label, "body": body})
    return days


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
        if args.no_email:
            logger.info("--no-email accepted; email layer is not enabled in 15.E.1")
        logger.info("Resolved UTC datetime: %s", resolved_utc.isoformat())
        resolved_gfs_cycle = resolve_gfs_cycle(resolved_utc)
        resolved_cmems_layer = resolve_cmems_layer(resolved_utc)
        request_dt_utc = datetime.now(timezone.utc)
        output_path = build_output_filename(
            start_dt_utc=resolved_utc,
            request_dt_utc=request_dt_utc,
            output_dir=OUTPUT_DIR_DEFAULT,
            force=args.force,
        )
        manifest = read_manifest(MANIFEST_PATH)
        _resolve_storage_paths(manifest, resolved_gfs_cycle, resolved_cmems_layer, logger)
        logger.info("Resolved GFS cycle UTC: %s", resolved_gfs_cycle.isoformat())
        logger.info("Resolved CMEMS layer date: %s", resolved_cmems_layer.isoformat())
        logger.info("Resolved output filename (DT-14-T): %s", output_path)

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
            print(f"  output_filename: {output_path}")
            _run_pipeline(
                resolved_utc=resolved_utc,
                gfs_cycle=resolved_gfs_cycle,
                cmems_layer=resolved_cmems_layer,
                output_path=output_path,
                logger=logger,
                dry_run=True,
            )
            return 0

        _run_pipeline(
            resolved_utc=resolved_utc,
            gfs_cycle=resolved_gfs_cycle,
            cmems_layer=resolved_cmems_layer,
            output_path=output_path,
            logger=logger,
            dry_run=False,
        )
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
