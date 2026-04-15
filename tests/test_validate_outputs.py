from datetime import datetime

import numpy as np
import pytest

from utils.validate_outputs import (
    DataQualityValidationError,
    ShapeValidationError,
    StructureValidationError,
    TemporalValidationError,
    assert_valid_for_bulletin,
    validate_meteo_output,
    validate_pipeline_outputs,
    validate_wave_output,
)


def _make_valid_meteo(nx: int = 3, ny: int = 4) -> dict[str, np.ndarray]:
    out: dict[str, np.ndarray] = {}
    out["Temp"] = np.full((nx, ny, 10), 10.0)
    for key in [
        "Rain",
        "Freeze_Rain",
        "Ice_Pell",
        "Snow",
        "Wind_Gust",
        "U_wind",
        "V_wind",
        "Vis",
    ]:
        out[key] = np.full((nx, ny, 5), 1.0)
    return out


def _make_valid_wave(nx: int = 3, ny: int = 4) -> tuple[np.ndarray, datetime, datetime]:
    wave = np.full((nx, ny, 5), 1.2)
    start = datetime(2026, 4, 15, 0, 0, 0)
    end = datetime(2026, 4, 20, 0, 0, 0)
    return wave, start, end


def test_validate_meteo_output_valid():
    report = validate_meteo_output(_make_valid_meteo(), strict=True)
    assert report["ok"] is True
    assert report["dataset"] == "meteo"
    assert report["errors"] == []


def test_validate_wave_output_valid():
    wave, start, end = _make_valid_wave()
    report = validate_wave_output(wave, start, end, strict=True)
    assert report["ok"] is True
    assert report["dataset"] == "wave"
    assert report["errors"] == []


def test_validate_meteo_missing_required_key():
    meteo = _make_valid_meteo()
    meteo.pop("Vis")
    report = validate_meteo_output(meteo, strict=True)
    assert report["ok"] is False
    assert any(issue["code"] == "missing_key" for issue in report["errors"])


def test_validate_meteo_empty_output():
    report = validate_meteo_output({}, strict=True)
    assert report["ok"] is False
    assert any(issue["code"] == "empty_output" for issue in report["errors"])


def test_validate_meteo_inconsistent_shapes():
    meteo = _make_valid_meteo()
    meteo["U_wind"] = np.full((99, 4, 5), 1.0)
    report = validate_meteo_output(meteo, strict=True)
    assert report["ok"] is False
    assert any(issue["code"] == "spatial_mismatch" for issue in report["errors"])


def test_validate_wave_invalid_date_range():
    wave, start, end = _make_valid_wave()
    report = validate_wave_output(wave, end, start, strict=True)
    assert report["ok"] is False
    assert any(issue["code"] == "invalid_date_range" for issue in report["errors"])


def test_validate_detects_all_nan_layer():
    meteo = _make_valid_meteo()
    meteo["Rain"][:, :, 1] = np.nan
    report = validate_meteo_output(meteo, strict=True)
    assert report["ok"] is False
    assert any(issue["code"] == "all_nan_layer" for issue in report["errors"])


def test_validate_detects_inf_values():
    meteo = _make_valid_meteo()
    meteo["Wind_Gust"][0, 0, 0] = np.inf
    report = validate_meteo_output(meteo, strict=True)
    assert report["ok"] is False
    assert any(issue["code"] == "non_finite" for issue in report["errors"])


def test_validate_detects_zero_filled_wave_layer():
    wave, start, end = _make_valid_wave()
    wave[:, :, 2] = 0.0
    report = validate_wave_output(wave, start, end, strict=False)
    assert any(issue["code"] == "zero_filled_layer" for issue in report["warnings"])


def test_validate_pipeline_strict_false_returns_report_no_raise():
    meteo = _make_valid_meteo()
    meteo.pop("Rain")
    report = validate_pipeline_outputs(meteo_data=meteo, wave_data=None, strict=False)
    assert isinstance(report, dict)
    assert report["ok"] is False
    assert len(report["errors"]) > 0


def test_assert_valid_for_bulletin_raises_on_critical_errors():
    meteo = _make_valid_meteo()
    meteo.pop("Temp")
    with pytest.raises(StructureValidationError):
        assert_valid_for_bulletin(meteo_data=meteo, strict=True)


def test_assert_valid_for_bulletin_raises_temporal_error():
    wave, start, end = _make_valid_wave()
    with pytest.raises(TemporalValidationError):
        assert_valid_for_bulletin(wave_data=(wave, end, start), strict=True)


def test_assert_valid_for_bulletin_raises_shape_error():
    meteo = _make_valid_meteo()
    meteo["Temp"] = np.full((3, 4, 9), 1.0)
    with pytest.raises(ShapeValidationError):
        assert_valid_for_bulletin(meteo_data=meteo, strict=True)


def test_assert_valid_for_bulletin_raises_data_quality_error():
    wave, start, end = _make_valid_wave()
    wave[:, :, 0] = np.nan
    with pytest.raises(DataQualityValidationError):
        assert_valid_for_bulletin(wave_data=(wave, start, end), strict=True)
