"""
Unified on-demand forecast entrypoint per ADR-001.

This module is the single CLI entrypoint for on-demand ingestion flow and will
replace `forecast_morning.py` / `forecast_evening.py`.
"""

from __future__ import annotations

import argparse
import configparser
import logging
import re
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

from utils.collect_meteo_data import collect_meteo_data
from utils.collect_wave_data import collect_wave_data
from utils.doc_builder import create_bulletin_doc as build_doc
from utils.manifest import ManifestCorruptedError, read_manifest
from utils.precip_statistics import precip_statistics
from utils.temp_statistics import temp_statistics_morning as temp_statistics
from utils.validate_outputs import NOMINAL_TOL_HOURS, ValidationError, assert_valid_for_bulletin
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
# DT-16-4: manifest is stale if cycle is older than this threshold
MANIFEST_STALE_THRESHOLD_HOURS: int = 7
CONFIG_PATH = Path("config.ini")
DEFAULT_FORECAST_HOURS = 120

logger = logging.getLogger(__name__)
email_sender: Any | None = None


class _EmailDeliveryError(Exception):
    """Raised when forecast_main.py fails to deliver the bulletin via email (ADR-001 §2)."""


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
        help=(
            "Dry-run: resolve parameters, log pipeline plan, do NOT call processing "
            "utilities, do NOT write .docx, do NOT send email."
        ),
    )
    parser.add_argument(
        "--strict-manifest",
        action="store_true",
        default=False,
        help=(
            "Exit 2 if manifest is missing, stale, or GFS storage path "
            "does not exist on disk. Disables fallback to floor-cycle "
            "disk search (ADR-001 §2, DT-16-4)."
        ),
    )
    parser.add_argument(
        "--no-email",
        action="store_true",
        help="Skip email delivery. Bulletin .docx is still produced and stored.",
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


def _compose_output_path_dry_run(start_dt_utc: datetime, output_dir: Path) -> Path:
    """Pure output path composition for dry-run; no filesystem side effects."""
    if start_dt_utc.tzinfo is None:
        raise ValueError("start_dt_utc must be timezone-aware")
    start_msk = start_dt_utc.astimezone(MSK_TZ)
    return output_dir / f"Прогноз_{start_msk:%Y%m%d}_{start_msk:%H%M}.docx"


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
    *,
    require_existing: bool = False,
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
        storage_root = gfs_block.get("storage_root")
        relative_path = gfs_block.get("relative_path")
        if isinstance(storage_root, str) and isinstance(relative_path, str):
            gfs_storage_path = Path(storage_root) / relative_path
            logger.info(
                "using GFS storage from manifest: %s / %s",
                storage_root,
                relative_path,
            )
            if require_existing and not gfs_storage_path.exists():
                raise FileNotFoundError(f"manifest GFS path does not exist: {gfs_storage_path}")

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
            if require_existing and not cmems_storage_path.exists():
                raise FileNotFoundError(f"manifest CMEMS storage_path does not exist: {cmems_storage_path}")

    return gfs_storage_path, cmems_storage_path


def _cycle_from_manifest(manifest: dict[str, Any]) -> datetime | None:
    """Return GFS cycle datetime from manifest, or None (ADR-002)."""
    gfs_block = manifest.get("gfs")
    if not isinstance(gfs_block, dict):
        return None
    cycle_str = gfs_block.get("latest_successful_cycle")
    if not isinstance(cycle_str, str):
        return None
    match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})T(00|06|12|18)Z", cycle_str)
    if match is None:
        return None
    return datetime(
        int(match.group(1)),
        int(match.group(2)),
        int(match.group(3)),
        int(match.group(4)),
        0,
        tzinfo=UTC_TZ,
    )


def _check_strict_manifest(
    manifest: dict[str, Any],
    resolved_utc: datetime,
    gfs_storage_path: Path | None,
    logger: logging.Logger,
) -> int | None:
    """
    In strict-manifest mode: validate manifest is present, fresh,
    and storage path exists. Return exit code or None if OK.
    DT-16-4, ADR-001 §2.
    """
    gfs_block = manifest.get("gfs")
    if not isinstance(gfs_block, dict):
        logger.error(
            "strict-manifest: GFS block missing in manifest; "
            "run ingest_gfs.py first (exit 2)"
        )
        return 2

    manifest_cycle = _cycle_from_manifest(manifest)
    if manifest_cycle is None:
        logger.error(
            "strict-manifest: cannot parse GFS cycle from manifest "
            "(exit 2)"
        )
        return 2

    age_hours = (resolved_utc - manifest_cycle).total_seconds() / 3600
    if age_hours > MANIFEST_STALE_THRESHOLD_HOURS:
        logger.error(
            "strict-manifest: manifest GFS cycle %s is stale "
            "(age=%.1fh > threshold=%dh); run ingest_gfs.py (exit 2)",
            manifest_cycle.isoformat(),
            age_hours,
            MANIFEST_STALE_THRESHOLD_HOURS,
        )
        return 2

    if gfs_storage_path is not None and not gfs_storage_path.exists():
        logger.error(
            "strict-manifest: GFS storage path does not exist: %s "
            "(exit 2)",
            gfs_storage_path,
        )
        return 2

    return None


def _read_manifest_for_run(path: Path, *, dry_run: bool, logger: logging.Logger) -> dict[str, Any]:
    try:
        return read_manifest(path)
    except ManifestCorruptedError as exc:
        if not dry_run:
            raise
        logger.warning("dry-run: manifest is corrupted, continuing with empty manifest: %s", exc)
        return {"schema_version": "1.0", "updated_at": datetime.now(timezone.utc).isoformat(), "gfs": None, "cmems": None}


def _run_pipeline(
    *,
    resolved_utc: datetime,
    gfs_cycle: datetime,
    cmems_layer: date,
    output_path: Path,
    logger: logging.Logger,
    dry_run: bool,
    gfs_storage_path: Path | None = None,
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
    if gfs_storage_path is not None:
        meteo = collect_meteo_data(
            run_date=gfs_run_date,
            cycle=cycle,
            gfs_data_dir=str(gfs_storage_path),
        )
    else:
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


def _emit_pipeline_plan(*, cycle: str, gfs_run_date: str, cmems_run_date: str, output_path: Path) -> None:
    _write_cli_line("[dry-run] pipeline plan:")
    _write_cli_line(f"1) collect_meteo_data(...): cycle={cycle}, rundate={gfs_run_date}")
    _write_cli_line(f"2) collect_wave_data(...): rundate={cmems_run_date}")
    _write_cli_line("3) assert_valid_for_bulletin(meteo, wave, strict=True)")
    _write_cli_line("4) temp_statistics / wind_statistics / precip_statistics")
    _write_cli_line(f"5) build_doc(...) -> {output_path}")
    _write_cli_line("email: skipped (dry-run; email layer not invoked)")


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


def _write_cli_line(message: str) -> None:
    sys.stdout.write(f"{message}\n")


def _load_config(path: Path = CONFIG_PATH) -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    read_ok = cfg.read(path, encoding="utf-8")
    if not read_ok:
        raise _EmailDeliveryError(f"Config file is not readable: {path}")
    return cfg


def _maybe_send_email(*, output_path: Path, resolved_utc: datetime, logger: logging.Logger) -> None:
    """Send the generated bulletin via existing email sender API (ADR-001 §2)."""
    global email_sender
    if email_sender is None:
        from utils import email_sender as email_sender_module

        email_sender = email_sender_module

    try:
        cfg = _load_config()
        email_cfg = cfg["Email"]
        ok = email_sender.send_bulletin(
            docx_path=str(output_path),
            recipient=email_cfg["recipient"],
            smtp_host=email_cfg["smtp_host"],
            smtp_port=int(email_cfg["smtp_port"]),
            login=email_cfg["login"],
            password=email_cfg["password"],
            bulletin_type="on-demand",
            run_date=resolved_utc.astimezone(MSK_TZ),
        )
        if not ok:
            raise _EmailDeliveryError("send_bulletin returned False")
    except _EmailDeliveryError:
        raise
    except Exception as exc:
        raise _EmailDeliveryError(str(exc)) from exc

    logger.info("forecast_main: email delivered for %s", output_path)


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
        request_dt_utc = datetime.now(timezone.utc)
        if args.dry_run:
            output_path = _compose_output_path_dry_run(
                start_dt_utc=resolved_utc,
                output_dir=OUTPUT_DIR_DEFAULT,
            )
        else:
            output_path = build_output_filename(
                start_dt_utc=resolved_utc,
                request_dt_utc=request_dt_utc,
                output_dir=OUTPUT_DIR_DEFAULT,
                force=args.force,
            )
        manifest = _read_manifest_for_run(MANIFEST_PATH, dry_run=args.dry_run, logger=logger)
        manifest_cycle = _cycle_from_manifest(manifest)
        if manifest_cycle is not None:
            effective_gfs_cycle = manifest_cycle
            if manifest_cycle != resolved_gfs_cycle:
                logger.info(
                    "using GFS cycle from manifest: %s (floor would be %s)",
                    _format_cycle_for_events(manifest_cycle),
                    _format_cycle_for_events(resolved_gfs_cycle),
                )
        else:
            effective_gfs_cycle = resolved_gfs_cycle
        gfs_storage_path, cmems_storage_path = _resolve_storage_paths(
            manifest,
            effective_gfs_cycle,
            resolved_cmems_layer,
            logger,
            require_existing=not args.dry_run,
        )
        if args.strict_manifest:
            strict_exit = _check_strict_manifest(
                manifest=manifest,
                resolved_utc=resolved_utc,
                gfs_storage_path=gfs_storage_path,
                logger=logger,
            )
            if strict_exit is not None:
                return strict_exit
        logger.info("Resolved GFS cycle UTC: %s", effective_gfs_cycle.isoformat())
        logger.info("Resolved CMEMS layer date: %s", resolved_cmems_layer.isoformat())
        logger.info("Resolved output filename (DT-14-T): %s", output_path)

        if args.dry_run:
            _write_cli_line("[dry-run] forecast_main resolved parameters:")
            _write_cli_line(f"  input_date: {args.date}")
            _write_cli_line(f"  input_time: {args.time}")
            _write_cli_line(f"  input_tz: {args.tz}")
            _write_cli_line(f"  UTC datetime: {resolved_utc.isoformat()}")
            _write_cli_line(f"  gfs_cycle: {effective_gfs_cycle.isoformat()}")
            _write_cli_line(f"  cmems_layer: {resolved_cmems_layer.isoformat()}")
            _write_cli_line(f"  gfs_lag: {GFS_LAG_HOURS}h")
            _write_cli_line(f"  cmems_lag: {CMEMS_LAG_HOURS}h")
            _write_cli_line(f"  timeout_minutes: {args.timeout_minutes}")
            _write_cli_line(f"  polling_minutes: {args.polling_minutes}")
            _write_cli_line(f"  output_filename: {output_path}")
            _run_pipeline(
                resolved_utc=resolved_utc,
                gfs_cycle=effective_gfs_cycle,
                cmems_layer=resolved_cmems_layer,
                output_path=output_path,
                logger=logger,
                dry_run=True,
                gfs_storage_path=gfs_storage_path,
            )
            return 0

        _run_pipeline(
            resolved_utc=resolved_utc,
            gfs_cycle=effective_gfs_cycle,
            cmems_layer=resolved_cmems_layer,
            output_path=output_path,
            logger=logger,
            dry_run=False,
            gfs_storage_path=gfs_storage_path,
        )
        if args.no_email:
            logger.info("forecast_main: email skipped (--no-email)")
        else:
            _maybe_send_email(output_path=output_path, resolved_utc=resolved_utc, logger=logger)
        return 0
    except ValidationError as exc:
        logger.error("validation failed: %s", exc, exc_info=True)
        return 1
    except (FileNotFoundError, ManifestCorruptedError) as exc:
        logger.error("ingestion missing: %s", exc, exc_info=True)
        return 2
    except _EmailDeliveryError as exc:
        logger.error("email delivery failed: %s", exc, exc_info=True)
        return 3
    except ValueError as exc:
        logger.error("%s", exc)
        return 2
    except KeyboardInterrupt:
        logger.warning("Interrupted by user.")
        return 130
    except Exception as exc:
        logger.exception("internal error: %s", exc)
        return 10


if __name__ == "__main__":
    sys.exit(main())
