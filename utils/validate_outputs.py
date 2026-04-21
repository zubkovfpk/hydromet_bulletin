"""
Validation helpers for processed meteo/wave outputs.

The module validates outputs of:
- utils.collect_meteo_data.collect_meteo_data() -> dict[str, np.ndarray]
- utils.collect_wave_data.collect_wave_data() -> tuple[np.ndarray, datetime, datetime]
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

NOMINAL_TOL_HOURS: int = 3
# Нормативный tolerance валидации горизонта прогноза в часах
# (см. docs/project_context.md — Validation horizon semantics).
# Не менять без обновления docs.

class ValidationError(Exception):
    """Base class for validation failures."""


class StructureValidationError(ValidationError):
    """Raised when dataset structure/type/required keys are invalid."""


class ShapeValidationError(ValidationError):
    """Raised when array dimensions/shapes/time-depth are invalid."""


class DataQualityValidationError(ValidationError):
    """Raised when data quality checks fail critically."""


class TemporalValidationError(ValidationError):
    """Raised when temporal metadata is invalid."""


REQUIRED_METEO_KEYS = {
    "Temp",
    "Rain",
    "Freeze_Rain",
    "Ice_Pell",
    "Snow",
    "Wind_Gust",
    "U_wind",
    "V_wind",
    "Vis",
}

DAILY_METEO_KEYS = {
    "Rain",
    "Freeze_Rain",
    "Ice_Pell",
    "Snow",
    "Wind_Gust",
    "U_wind",
    "V_wind",
    "Vis",
}


def _base_report(dataset: str) -> dict[str, Any]:
    return {
        "ok": True,
        "dataset": dataset,
        "errors": [],
        "warnings": [],
        "stats": {
            "variables_checked": None,
            "time_steps": None,
            "date_start": None,
            "date_end": None,
        },
    }


def _make_issue(code: str, message: str, severity: str, path: str | None = None) -> dict[str, str]:
    issue = {"code": code, "message": message, "severity": severity}
    if path:
        issue["path"] = path
    return issue


def _add_error(report: dict[str, Any], code: str, message: str, path: str | None = None) -> None:
    report["errors"].append(_make_issue(code, message, "error", path))
    report["ok"] = False


def _add_warning(report: dict[str, Any], code: str, message: str, path: str | None = None) -> None:
    report["warnings"].append(_make_issue(code, message, "warning", path))


def _check_array_basic(report: dict[str, Any], arr: Any, path: str, expected_ndim: int = 3) -> np.ndarray | None:
    if not isinstance(arr, np.ndarray):
        _add_error(report, "invalid_type", f"Expected numpy.ndarray, got {type(arr).__name__}.", path)
        return None
    if arr.ndim != expected_ndim:
        _add_error(report, "invalid_ndim", f"Expected {expected_ndim}D array, got {arr.ndim}D.", path)
        return None
    if 0 in arr.shape:
        _add_error(report, "empty_axis", f"Array contains empty axis: shape={arr.shape}.", path)
        return None
    if np.any(np.isinf(arr)):
        _add_error(report, "non_finite", "Array contains inf/-inf values.", path)
    return arr


def _detect_all_nan_layers(report: dict[str, Any], arr: np.ndarray, path: str) -> None:
    for idx in range(arr.shape[2]):
        layer = arr[:, :, idx]
        if np.isnan(layer).all():
            _add_error(report, "all_nan_layer", f"Layer {idx} is fully NaN.", f"{path}[:,:,{idx}]")


def _warn_high_nan_ratio(report: dict[str, Any], arr: np.ndarray, path: str, threshold: float = 0.95) -> None:
    ratio = float(np.isnan(arr).sum()) / float(arr.size)
    if ratio >= threshold:
        _add_warning(
            report,
            "high_nan_ratio",
            f"NaN ratio is high ({ratio:.2%}, threshold={threshold:.0%}).",
            path,
        )


def _warn_uniform_field(report: dict[str, Any], arr: np.ndarray, path: str) -> None:
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return
    if float(np.nanmax(finite)) == float(np.nanmin(finite)):
        _add_warning(report, "uniform_field", "Field appears fully uniform.", path)


def _validate_dates(
    report: dict[str, Any],
    start_date: Any,
    end_date: Any,
    strict: bool,
    forecast_hours: int | None,
    tol_hours: int = 0,
) -> None:
    if not isinstance(start_date, datetime) or not isinstance(end_date, datetime):
        _add_error(report, "invalid_date_type", "start_date and end_date must be datetime.", "wave_data")
        return

    if forecast_hours is None:
        _add_error(
            report,
            "missing_forecast_hours",
            "forecast_hours must be provided explicitly for wave temporal validation.",
            "wave_data",
        )
        return

    report["stats"]["date_start"] = start_date.isoformat()
    report["stats"]["date_end"] = end_date.isoformat()
    horizon_hours_actual = (end_date - start_date).total_seconds() / 3600.0
    logger.info(
        "Wave horizon check: start=%s end=%s actual=%.1fh expected=%dh tolerance=%dh",
        start_date.isoformat(),
        end_date.isoformat(),
        horizon_hours_actual,
        forecast_hours,
        tol_hours,
    )
    if end_date < start_date:
        _add_error(report, "invalid_date_range", "start_date is after end_date.", "wave_data")
    elif horizon_hours_actual < (float(forecast_hours) - float(tol_hours)):
        code = "suspicious_horizon"
        msg = (
            f"Wave horizon looks suspicious: {horizon_hours_actual:.1f}h < expected "
            f"{forecast_hours}h (tolerance {tol_hours}h)."
        )
        if strict:
            _add_error(report, code, msg, "wave_data")
        else:
            _add_warning(report, code, msg, "wave_data")


def validate_meteo_output(data: Any, *, strict: bool = True) -> dict[str, Any]:
    """
    Validate processed meteo output from collect_meteo_data().

    Returns a report dict with errors/warnings and never raises.
    """
    report = _base_report("meteo")

    if not isinstance(data, dict):
        _add_error(report, "invalid_container", "Meteo output must be a dict.", "meteo_data")
        return report
    if not data:
        _add_error(report, "empty_output", "Meteo output is empty.", "meteo_data")
        return report

    report["stats"]["variables_checked"] = len(data)

    missing = sorted(REQUIRED_METEO_KEYS.difference(data.keys()))
    if missing:
        _add_error(report, "missing_key", f"Missing required keys: {', '.join(missing)}.", "meteo_data")

    reference_shape_xy: tuple[int, int] | None = None
    for key in sorted(REQUIRED_METEO_KEYS.intersection(data.keys())):
        arr = _check_array_basic(report, data[key], key)
        if arr is None:
            continue

        if reference_shape_xy is None:
            reference_shape_xy = arr.shape[:2]
        elif arr.shape[:2] != reference_shape_xy:
            _add_error(
                report,
                "spatial_mismatch",
                f"Spatial shape {arr.shape[:2]} differs from reference {reference_shape_xy}.",
                key,
            )

        expected_depth = 10 if key == "Temp" else 5
        if arr.shape[2] != expected_depth:
            _add_error(
                report,
                "invalid_time_depth",
                f"Expected time-depth {expected_depth}, got {arr.shape[2]}.",
                key,
            )

        _detect_all_nan_layers(report, arr, key)
        _warn_high_nan_ratio(report, arr, key)
        _warn_uniform_field(report, arr, key)

        if key in {"Rain", "Freeze_Rain", "Ice_Pell", "Snow"}:
            finite = arr[np.isfinite(arr)]
            if finite.size and np.any((finite < 0) | (finite > 1)):
                _add_warning(
                    report,
                    "categorical_range_suspect",
                    "Categorical precipitation values are outside [0, 1].",
                    key,
                )

    report["stats"]["time_steps"] = int(data["Temp"].shape[2]) if isinstance(data.get("Temp"), np.ndarray) and data["Temp"].ndim == 3 else None
    return report


def validate_wave_output(
    wave: Any,
    start_date: Any,
    end_date: Any,
    *,
    strict: bool = True,
    forecast_hours: int | None = None,
    tol_hours: int = 0,
) -> dict[str, Any]:
    """
    Validate processed wave output from collect_wave_data().

    Returns a report dict with errors/warnings and never raises.
    """
    report = _base_report("wave")
    arr = _check_array_basic(report, wave, "wave")
    if arr is None:
        return report

    report["stats"]["time_steps"] = int(arr.shape[2])
    _validate_dates(report, start_date, end_date, strict, forecast_hours, tol_hours)

    if arr.shape[2] != 5:
        _add_error(report, "invalid_time_depth", f"Expected wave time-depth 5, got {arr.shape[2]}.", "wave")

    _detect_all_nan_layers(report, arr, "wave")
    _warn_high_nan_ratio(report, arr, "wave")
    _warn_uniform_field(report, arr, "wave")

    for idx in range(arr.shape[2]):
        layer = arr[:, :, idx]
        finite = layer[np.isfinite(layer)]
        if finite.size == 0:
            continue
        if np.all(finite == 0):
            msg = f"Wave layer {idx} is fully zero-filled."
            if strict:
                _add_error(report, "zero_filled_layer", msg, f"wave[:,:,{idx}]")
            else:
                _add_warning(report, "zero_filled_layer", msg, f"wave[:,:,{idx}]")
    return report


def validate_pipeline_outputs(
    *,
    meteo_data: Any = None,
    wave_data: Any = None,
    strict: bool = True,
    forecast_hours: int | None = None,
    tol_hours: int = 0,
) -> dict[str, Any]:
    """
    Validate meteo and/or wave outputs and return one combined report.

    wave_data is expected as tuple: (wave, start_date, end_date).
    """
    pipeline = _base_report("pipeline")
    pipeline["stats"]["variables_checked"] = 0

    if meteo_data is not None:
        meteo_report = validate_meteo_output(meteo_data, strict=strict)
        pipeline["errors"].extend(meteo_report["errors"])
        pipeline["warnings"].extend(meteo_report["warnings"])
        checked = meteo_report["stats"].get("variables_checked")
        if isinstance(checked, int):
            pipeline["stats"]["variables_checked"] += checked
        if pipeline["stats"]["time_steps"] is None:
            pipeline["stats"]["time_steps"] = meteo_report["stats"].get("time_steps")

    if wave_data is not None:
        if (
            not isinstance(wave_data, tuple)
            or len(wave_data) != 3
        ):
            _add_error(
                pipeline,
                "invalid_wave_payload",
                "wave_data must be tuple (wave, start_date, end_date).",
                "wave_data",
            )
        else:
            wave, start_date, end_date = wave_data
            wave_report = validate_wave_output(
                wave,
                start_date,
                end_date,
                strict=strict,
                forecast_hours=forecast_hours,
                tol_hours=tol_hours,
            )
            pipeline["errors"].extend(wave_report["errors"])
            pipeline["warnings"].extend(wave_report["warnings"])
            pipeline["stats"]["date_start"] = wave_report["stats"].get("date_start")
            pipeline["stats"]["date_end"] = wave_report["stats"].get("date_end")

    if meteo_data is None and wave_data is None:
        _add_error(pipeline, "empty_input", "At least one dataset must be provided.", "pipeline")

    if pipeline["errors"]:
        pipeline["ok"] = False
    return pipeline


def assert_valid_for_bulletin(
    *,
    meteo_data: Any = None,
    wave_data: Any = None,
    strict: bool = True,
    forecast_hours: int | None = None,
    tol_hours: int = 0,
) -> None:
    """
    Raise ValidationError subclass when critical validation errors are found.
    """
    report = validate_pipeline_outputs(
        meteo_data=meteo_data,
        wave_data=wave_data,
        strict=strict,
        forecast_hours=forecast_hours,
        tol_hours=tol_hours,
    )
    if report["ok"]:
        return

    codes = {item["code"] for item in report["errors"]}
    summary = summarize_validation(report)
    if {"invalid_date_type", "invalid_date_range", "suspicious_horizon", "missing_forecast_hours"} & codes:
        raise TemporalValidationError(summary)
    if {"invalid_ndim", "empty_axis", "spatial_mismatch", "invalid_time_depth"} & codes:
        raise ShapeValidationError(summary)
    if {"all_nan_layer", "non_finite", "zero_filled_layer"} & codes:
        raise DataQualityValidationError(summary)
    if {
        "invalid_container",
        "empty_output",
        "missing_key",
        "invalid_wave_payload",
        "empty_input",
        "invalid_type",
    } & codes:
        raise StructureValidationError(summary)
    raise ValidationError(summary)


def summarize_validation(report: dict[str, Any]) -> str:
    """
    Build short human-readable summary from validation report.
    """
    dataset = report.get("dataset", "unknown")
    errors = report.get("errors", [])
    warnings = report.get("warnings", [])
    if not errors and not warnings:
        return f"[{dataset}] Validation passed with no issues."

    parts = [f"[{dataset}] errors={len(errors)}, warnings={len(warnings)}"]
    if errors:
        parts.append("first_error=" + errors[0].get("message", "n/a"))
    if warnings:
        parts.append("first_warning=" + warnings[0].get("message", "n/a"))
    return "; ".join(parts)
