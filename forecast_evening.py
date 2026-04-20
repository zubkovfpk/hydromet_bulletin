"""
forecast_evening.py
Вечерний гидрометеорологический бюллетень (19:00 MSK).
Формирует прогноз на 5 суток, сохраняет .docx и отправляет на email.

Запуск:
    python forecast_evening.py [--date YYYYMMDD] [--config config.ini]
"""

import argparse
import configparser
import logging
import time
import numpy as np
from datetime import datetime, timedelta, timezone
from pathlib import Path

from utils import (
    collect_meteo_data,
    collect_wave_data,
    wind_statistics,
    precip_statistics,
    temp_statistics_evening,
    create_bulletin_doc,
    send_bulletin,
)
from utils.collect_wave_data import _discover_cmems_nc_files
from utils.downloaders.cmems_downloader import resolve_cmems_forecast_hours
from utils.validate_outputs import assert_valid_for_bulletin

# ── Логирование ──────────────────────────────────────────────────────────────
logger = logging.getLogger(__name__)


def _resolve_effective_forecast_hours(
    cfg: configparser.ConfigParser,
    forecast_hours_override: int | None,
) -> int:
    if forecast_hours_override is not None:
        return int(forecast_hours_override)
    return int(resolve_cmems_forecast_hours(cfg, logger))


def _resolve_run_date_for_dry_run(
    *,
    explicit_run_date: str | None,
    base_dir: str,
    cmems_storage_subdir: str,
) -> str:
    if explicit_run_date:
        logger.info("Dry-run run_date=%s (explicit --date, fallback disabled)", explicit_run_date)
        return explicit_run_date

    today_utc = datetime.now(timezone.utc).date()
    today_str = today_utc.strftime("%Y%m%d")
    files_today, _ = _discover_cmems_nc_files(
        base_dir=base_dir,
        run_date=today_str,
        cmems_storage_subdir=cmems_storage_subdir,
        legacy_waves_dir="waves",
    )
    if files_today:
        logger.info("Dry-run run_date=today=%s (UTC)", today_str)
        return today_str

    prev_str = (today_utc - timedelta(days=1)).strftime("%Y%m%d")
    files_prev, _ = _discover_cmems_nc_files(
        base_dir=base_dir,
        run_date=prev_str,
        cmems_storage_subdir=cmems_storage_subdir,
        legacy_waves_dir="waves",
    )
    if files_prev:
        logger.info("Dry-run run_date=today-1=%s (UTC) — no CMEMS for today", prev_str)
        return prev_str

    raise FileNotFoundError("No CMEMS .nc for today UTC nor today-1; check ingestion")


def _configure_logging(cfg: configparser.ConfigParser) -> None:
    base_dir = cfg.get("General", "basedir", fallback=".")
    log_file = (
        cfg.get("General", "log_file", fallback="").strip()
        or cfg.get("Logging", "log_file", fallback="").strip()
    )
    log_path = Path(log_file) if log_file else Path(base_dir) / "logs" / "hydromet.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_path, encoding="utf-8"),
        ],
        force=True,
    )


def run_evening(cfg: configparser.ConfigParser,
                run_date: str | None = None,
                forecast_hours_override: int | None = None) -> str | None:
    """
    Основная функция вечернего бюллетеня.

    Parameters
    ----------
    cfg      : ConfigParser — загруженный config.ini
    run_date : str | None   — 'YYYYMMDD'; если None — сегодня

    Returns
    -------
    Путь к созданному .docx или None при ошибке.
    """
    t_start = time.time()
    _configure_logging(cfg)
    base_dir = cfg.get("General", "basedir", fallback=".")
    shapefile_dir = cfg.get(
        "General",
        "shapefile_dir",
        fallback=str(Path(base_dir) / "data" / "shapefiles"),
    )
    out_dir  = cfg.get("General", "output_dir", fallback="./output")
    gfs_storage_subdir = cfg.get("GFS_STORAGE", "GFS_OUTPUT_DIR", fallback="data/storage/gfs")
    cmems_storage_subdir = cfg.get("CMEMS_STORAGE", "CMEMS_OUTPUT_DIR", fallback="data/storage/cmems")
    gfs_cycle = cfg.get("GFS_SOURCES", "GFS_CYCLES", fallback="00z").split(",")[0].strip()
    effective_forecast_hours = _resolve_effective_forecast_hours(cfg, forecast_hours_override)
    if forecast_hours_override is not None:
        logger.info("CMEMS forecast_hours=%d (from CLI override)", effective_forecast_hours)
    else:
        logger.info("CMEMS forecast_hours=%d (from config)", effective_forecast_hours)
    effective_run_date = _resolve_run_date_for_dry_run(
        explicit_run_date=run_date,
        base_dir=base_dir,
        cmems_storage_subdir=cmems_storage_subdir,
    )

    try:
        # ── 1. Загрузка данных ────────────────────────────────────────────
        logger.info("=== Вечерний бюллетень: старт ===")
        logger.info("Загрузка метеоданных GFS...")
        meteo = collect_meteo_data(
            base_dir=base_dir,
            shapefile_dir=shapefile_dir,
            run_date=effective_run_date,
            cycle=gfs_cycle,
            gfs_storage_subdir=gfs_storage_subdir,
        )

        logger.info("Загрузка данных о волнении CMEMS...")
        HWave, start_date, end_date = collect_wave_data(
            base_dir=base_dir,
            shapefile_dir=shapefile_dir,
            run_date=effective_run_date,
            cmems_storage_subdir=cmems_storage_subdir,
        )
        assert_valid_for_bulletin(
            meteo_data=meteo,
            wave_data=(HWave, start_date, end_date),
            strict=True,
            forecast_hours=effective_forecast_hours,
        )

        # ── 2. Формирование контента ──────────────────────────────────────
        n_days = int((end_date - start_date).days)
        dtime  = [start_date + timedelta(days=d) for d in range(n_days + 1)]
        days_content = []

        for n in range(len(dtime) - 1):
            d1 = dtime[n].strftime("%d.%m.%Y")
            d2 = dtime[n + 1].strftime("%d.%m.%Y")
            period_label = f"С 19:00 {d1} до 19:00 {d2}"

            wind_dir, wind_min, wind_max = wind_statistics(
                meteo["U_wind"][:, :, n], meteo["V_wind"][:, :, n]
            )
            gust = int(round(float(np.nanmax(meteo["Wind_Gust"][:, :, n]))))

            precipitation = precip_statistics(
                meteo["Freeze_Rain"][:, :, n], meteo["Ice_Pell"][:, :, n],
                meteo["Rain"][:, :, n],        meteo["Snow"][:, :, n],
            )

            vis_min = int(round(float(np.nanmin(meteo["Vis"][:, :, n])) / 1000))
            vis_max = int(round(float(np.nanmax(meteo["Vis"][:, :, n])) / 1000))

            wave_min = round(float(np.nanmin(HWave[:, :, n])), 1)
            wave_max = round(float(np.nanmax(HWave[:, :, n])), 1)

            temperature = temp_statistics_evening(
                meteo["Temp"][:, :, n], meteo["Temp"][:, :, n + 1]
            )

            body = (
                f"Ветер {wind_dir} {wind_min}-{wind_max} м/с, "
                f"возможны порывы до {gust} м/с. "
                f"{precipitation} "
                f"Видимость {vis_min}-{vis_max} км. "
                f"Высота волны {wave_min}-{wave_max} м. "
                f"{temperature}"
            )
            days_content.append({"period_label": period_label, "body": body})
            logger.info(f"  [{n+1}/{len(dtime)-1}] {period_label} — OK")

        # ── 3. Сохранение .docx ───────────────────────────────────────────
        start_str    = start_date.strftime("%d.%m.%Y")
        header_title = "ГИДРОМЕТЕОРОЛОГИЧЕСКИЙ БЮЛЛЕТЕНЬ"
        header_date  = f"от {start_str} 19:00"

        Path(out_dir).mkdir(parents=True, exist_ok=True)
        filename = f"Прогноз_вечер_{start_date.strftime('%Y%m%d')}.docx"
        out_path = str(Path(out_dir) / filename)

        create_bulletin_doc(
            output_path=out_path,
            bulletin_type="evening",
            header_title=header_title,
            header_date_line=header_date,
            days=days_content,
        )
        logger.info(f"Файл сохранён: {out_path}")

        # ── 4. Отправка на email ──────────────────────────────────────────
        ok = send_bulletin(
            docx_path=out_path,
            recipient=cfg.get("Email", "recipient"),
            smtp_host=cfg.get("Email", "smtp_host"),
            smtp_port=cfg.getint("Email", "smtp_port"),
            login=cfg.get("Email", "login"),
            password=cfg.get("Email", "password"),
            bulletin_type="вечерний",
            run_date=start_date,
        )
        if ok:
            logger.info("Email успешно отправлен.")
        else:
            logger.warning("Email НЕ отправлен — проверьте лог выше.")

        elapsed = time.time() - t_start
        logger.info(f"=== Готово. Время выполнения: {elapsed:.1f} с. ===")
        return out_path

    except Exception as e:
        logger.exception(f"Критическая ошибка: {e}")
        return None


# ── CLI ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Вечерний метеобюллетень")
    parser.add_argument("--date",   default=None,         help="Дата YYYYMMDD")
    parser.add_argument("--forecast-hours", type=int, default=None, help="Горизонт прогноза CMEMS в часах")
    parser.add_argument("--config", default="config.ini", help="Путь к config.ini")
    args = parser.parse_args()

    cfg = configparser.ConfigParser()
    cfg.read(args.config, encoding="utf-8")

    run_evening(cfg=cfg, run_date=args.date, forecast_hours_override=args.forecast_hours)
